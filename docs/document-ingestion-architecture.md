# Document ingestion architecture

This document explains the modern, route-based document parsing pipeline that sits
in front of the existing RAG stack. It is a **foundation**: the abstractions,
routing, quality gating, and structure-aware chunking are in place and tested, but
the reliability numbers on real Persian/English enterprise documents still have to
be measured (see [Benchmarking](#what-still-needs-real-documents)).

## Why route-based

Real-world PDFs are not one thing. A single upload may contain digital text pages,
scanned pages, multi-column layouts, and tables — sometimes in the same file, in
Persian, English, or both. No single extractor is best for all of them:

- **Digital PDF / DOCX** → native text and layout engines (fast, exact).
- **Scanned pages** → OCR with preprocessing and region detection.
- **Tables** → structure-preserving extraction, not blind flattening.

So the pipeline chooses an extractor per document (with a fallback chain) instead
of forcing everything through one parser. Selection is explicit and testable
rather than implicit.

## Pipeline shape

```
File uploaded
  → extraction router               (eda.extractors.router)
      → extractor implementation     (Docling / native PDF / adaptive OCR / DOCX / XLSX / image OCR)
          → canonical representation (eda.ingestion_schema: DocumentManifest, PageResult, BlockResult, TableResult)
              → quality scoring      (eda.quality: 0–100 + verdict, page/document)
                  → fallback or needs_review if low quality
                      → structure-aware chunking  (eda.structure_chunker)
                          → embedding + Qdrant     (eda.index.ingest_chunks — unchanged)
```

The load-bearing rule: **parsing produces a canonical structured document first,
and only accepted content becomes chunks.** Low-quality extraction is never
silently embedded.

## Canonical representation comes before chunking

Everything an extractor produces is expressed as schema-validated objects in
`src/eda/ingestion_schema.py`:

- `DocumentManifest` — public document metadata only. No source path, no document
  text, no secrets (validators enforce this).
- `PageResult` — one page: `native_text`, `ocr_text`, derived `index_text`,
  reading-ordered `regions`, semantic `blocks`, an `OCRDecision`, provenance, and
  a `processing_status` (`accepted` / `needs_review` / `failed`).
- `BlockResult` — a semantic unit (`heading`, `paragraph`, `list_item`, `table`,
  `key_value`, `image_text`, `header`, `footer`, `caption`, `unknown`) with a
  stable `block_id`, reading order, extraction route, source layer, and optional
  bbox / language / table payload.
- `TableResult` / `TableCell` — structure-preserving tables plus a lossy Markdown
  rendering used only as a reading aid.

Identifiers (`src/eda/identifiers.py`) are deterministic UUID5s derived from a
tenant-scoped logical key, the content SHA-256, and page/block order. Re-ingesting
identical content yields identical IDs (idempotent overwrite, never duplication),
and IDs reveal neither text nor hashes.

Deciding structure **before** chunking is what lets chunking respect real
boundaries: a heading leads its section, a table becomes its own chunk with
`header: value` row context, and citations can point at a specific page and block.

## How quality scoring works

`src/eda/quality.py` computes a normalized 0–100 score at block, page, and document
level from language-agnostic signals: meaningful-character ratio, garbage-character
ratio, word repetition, text length, and — where available — OCR confidence,
cross-layer (native vs. OCR) agreement, and the OCR quality gate result.

Scores map to a four-level verdict (defaults, documented in `QualityThresholds`):

| Score  | Level                   | Processing status |
|--------|-------------------------|-------------------|
| 90–100 | `accepted`              | `accepted`        |
| 70–89  | `accepted_with_warning` | `accepted`        |
| 40–69  | `needs_review`          | `needs_review`    |
| 0–39   | `failed`                | `failed`          |

The central guarantee: a page can **never be scored above the ceiling its own
pipeline status allows**. A page the extractor flagged `needs_review` stays
`needs_review` even if its text is clean, and garbage text can never reach the
accepted band. The structure-aware chunker refuses to convert `failed` pages, and
`needs_review` pages, into embeddable chunks unless `allow_needs_review=True` is
passed explicitly.

> Thresholds are provisional operating defaults, not validated OCR benchmarks.

## Persian / English handling

- **Normalization** — presentation-form variants are folded to standard forms
  (`ي/ی`, `ك/ک`), tatweel and zero-width joiners handled, digits/whitespace
  normalized (`eda.ocr_quality.normalize_ocr_text`,
  `eda.ocr_evaluation.normalize_persian_for_evaluation`). Metrics are always
  computed on normalized text so they don't lie.
- **RTL reading order & multi-column** — the adaptive OCR route detects regions
  and orders columns top-to-bottom, right-to-left for RTL pages
  (`eda.adaptive_ocr.order_region_boxes`).
- **Mixed language** — language is detected per block/chunk (`persian_ratio`),
  never per tenant; one file may mix Persian and English.
- **Digits & ZWNJ** — Persian/Arabic/Latin digits and the zero-width non-joiner
  are handled in normalization and evaluation.
- **Poor scans / OCR garbage / repeated text** — caught by the quality signals and
  pushed to `needs_review`/`failed` rather than embedded.

## Where Docling fits

`DoclingExtractor` (`eda.extractors.docling_extractor`) is a first-class candidate
for **digital PDFs and DOCX**, especially table-heavy documents. It is an adapter
*behind* the extractor interface — the rest of the pipeline never imports Docling.
The engine is imported lazily; if it is missing or a conversion fails, the router
falls back to the native/adaptive routes. Docling block bounding boxes are
intentionally left unset for now (coordinate origins vary by backend), so its
mapping still needs validation against real documents.

## Where adaptive OCR fits

`AdaptivePdfExtractor` wraps the existing `eda.adaptive_ocr` engine: page
classification → OCR candidate generation (PSM / language / preprocessing sweeps) →
deterministic quality gate and route selection (full-page vs. region OCR) →
canonical `PageResult`s. It is the route for **scanned and mixed PDFs** and is the
fallback when native/Docling extraction is insufficient. It requires a local
Tesseract with the `fas` and `eng` language packs; without them it reports
`unavailable` and the router records a clean fallback.

## The extractor interface and router

```python
class DocumentExtractor:
    route: ExtractorRoute
    def supports(path, mime_type=None, extension=None) -> bool
    def extract(path, *, options: ExtractionOptions) -> ExtractedDocument
```

`ExtractionRouter` (`eda.extractors.router`) builds the ordered list of supporting
extractors for a file and tries them until one produces *sufficient* output (at
least one accepted or reviewable page). `default_router()` leads with fast native /
office parsers and keeps Docling and OCR as fallbacks; `docling_first_router()`
leads with Docling for PDF/DOCX. Every returned `ExtractedDocument` carries its own
`QualityReport` and the warnings describing which routes were skipped and why.

## Structure-aware chunking

`eda.structure_chunker.structure_chunks(document, acl_groups=...)` converts accepted
canonical pages into the existing `Chunk` objects consumed by
`eda.index.ingest_chunks()` — so the embedding and Qdrant layers are unchanged.
It groups reading-ordered blocks into word-budgeted chunks (headings lead their
section; tables are emitted as their own chunk with preserved row/column context)
and stamps every chunk with full provenance in `location`: `document_id`,
`revision_id`, `page_id`, `block_ids`, page number, extraction route, quality score,
source name/type — plus `tenant_id` and `acl_groups`.

### Security invariants (unchanged)

- **ACL is authoritative and required.** `tenant_id` and `acl_groups` come from the
  authenticated uploader (the manifest / options), never from document content.
  XLSX extraction still refuses to run without an explicit non-empty ACL scope.
- **No private paths or secrets in public metadata.** Manifest, region, and block
  metadata validators reject absolute paths, secret-looking keys, and duplicated
  document/OCR text.

## What still needs real documents

The repository's sample PDFs are random test files, **not** a quality benchmark.
The full corpus plan, ground-truth levels, metrics, and acceptance criteria live in
[`benchmark-corpus-plan.md`](./benchmark-corpus-plan.md). In short, to measure real
reliability:

1. Place real Persian/English enterprise documents in a local, git-ignored folder.
2. Run the report harness and read the measured signals (it never fabricates
   confidence):

   ```bash
   uv run python scripts/extraction_report.py path/to/benchmark
   uv run python scripts/extraction_report.py path/to/benchmark --prefer-docling --json
   ```

   Each row reports the chosen route, page counts by verdict, average quality
   score, table count, OCR usage, warnings, and errors; the summary aggregates the
   corpus.
3. Use `evaluation/ocr/` fixtures (see `eda.evaluation_schema`) with ground truth
   to compute CER/WER and route/classification accuracy where labels exist.

Still open for validation with real data: Docling block bbox mapping, threshold
calibration in `eda.quality`, and OCR gate tuning for low-quality Persian scans.

## Enabling canonical ingestion in the Celery worker

The worker (`api/tasks.py`, task `ingest_document`) selects its pipeline from
`api/config.py`, driven entirely by environment variables. The switch is explicit,
validated at startup (invalid values raise immediately), and reversible.

| Variable | Values | Default | Meaning |
|----------|--------|---------|---------|
| `INGESTION_PIPELINE` | `legacy` / `canonical` / `docling_first` | `legacy` | Which pipeline the worker uses. |
| `INGESTION_ALLOW_NEEDS_REVIEW` | `true` / `false` | `false` | Canonical: also embed pages the quality gate flagged for review. |
| `INGESTION_MAX_CHUNK_WORDS` | integer ≥ 1 | `350` | Canonical: word budget for structure-aware chunking. |
| `INGESTION_FAIL_ON_ZERO_CHUNKS` | `true` / `false` | `true` | Canonical: fail the task loudly when extraction embeds nothing *and* there is no needs_review outcome. |

- **Enable canonical ingestion:** `INGESTION_PIPELINE=canonical` (uses
  `default_router()` — native/office first, Docling and OCR as fallback).
- **Enable Docling-first ingestion:** `INGESTION_PIPELINE=docling_first` (leads with
  Docling for PDF/DOCX; falls back to native/adaptive).
- **Roll back instantly:** `INGESTION_PIPELINE=legacy` — restores the exact prior
  behavior (`parse_any` → `_stamp_identity` → `ingest_chunks`).

Identity is unchanged in every mode: `tenant_id` and `acl_groups` come from the
authenticated uploader's token, are re-stamped onto every chunk, and are never read
from document content. XLSX still requires an explicit non-empty ACL scope.

### Job result fields

Legacy results keep exactly their prior shape (`chunks`, `source`, `tenant_id`).
Canonical results add (the `result` payload of `/documents/jobs/{id}`):

| Field | Meaning |
|-------|---------|
| `ingestion_pipeline` | `canonical` / `docling_first` |
| `extraction_route` | which extractor produced the document (`native_pdf`, `docling`, `adaptive_pdf_ocr`, …) |
| `ingestion_status` | `indexed` / `indexed_with_warnings` / `needs_review` / `failed` |
| `quality_score` / `quality_level` | 0–100 and its verdict band |
| `total_pages` / `accepted_pages` / `needs_review_pages` / `failed_pages` / `empty_pages` | page verdict counts |
| `table_count` | tables detected |
| `warnings` / `errors` | public-safe diagnostics (route fallbacks, gate reasons) |
| `embedded_chunks` (== `chunks`) | how many chunks were actually upserted |

**Why `needs_review` documents are not embedded by default.** A page the quality
gate flags for review is parsed but *not indexed*: the task returns SUCCESS with
`ingestion_status="needs_review"` and upserts nothing, so low-quality content never
silently enters retrieval. It is a business outcome, not a worker crash. Set
`INGESTION_ALLOW_NEEDS_REVIEW=true` to index reviewable pages anyway. A genuinely
empty extraction (nothing accepted, nothing to review) fails the task loudly under
the default `INGESTION_FAIL_ON_ZERO_CHUNKS=true`; a real inability to run any route
raises and surfaces as a normal Celery failure.

> Thresholds remain provisional. **Real Persian/English enterprise documents are
> still required to calibrate them** before these verdicts carry benchmark weight —
> the repository's sample PDFs are random test files, not evidence.

## Compatibility & scope

- The legacy path is **preserved and remains the default** — canonical ingestion is
  opt-in per the table above. `parse.py`'s adaptive mode also still routes through
  the canonical schema via `eda.ingestion_adapter`.
- Qdrant payloads are unchanged — the structure-aware chunker emits the same
  `Chunk` shape, only with richer `location` provenance.
- FastAPI, Celery, Redis, Qdrant, Ollama, and the bge-m3 embedding pipeline are
  untouched.
```
