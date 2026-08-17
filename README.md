# Enterprise Docs Assistant

A multi-tenant RAG system with access-control-aware retrieval. It answers natural-language
questions with citations back to the source document and location, while guaranteeing that no
tenant ever sees another tenant's data and no user retrieves documents outside their permission
groups.

The defining property: **two users asking the identical question receive different answers from
different documents**, because access control is enforced inside the vector search rather than
around it.

---

## Why this exists

Most RAG demos index one clean corpus and stop. Real enterprise deployments need two things that
reference implementations almost never have, and both are treated here as the primary engineering
problem — validated by test, not asserted:

1. **Multi-tenancy** — several organizations share one system; their data must never cross.
2. **ACL-aware retrieval** — access filtering happens *inside* the vector search. Post-filtering
   (retrieve, then drop disallowed results) silently truncates the result set and the model
   answers from whatever survives.

---

## Features

- **Multi-tenant isolation** with an adversarial leak-test suite and a negative control.
- **Group-level ACL** enforced as a pre-filter inside Qdrant.
- **Two orthogonal authorization systems**: ACL (which documents) and dynamic RBAC (which
  features), kept strictly separate.
- **Multi-format ingestion** through a parser registry — PDF, XLSX, DOCX, and images (OCR) — where
  adding a format is one parser plus one line.
- **Async document upload** via Celery, with identity stamped from the uploader's token.
- **Dense retrieval** in the production API. Hybrid BM25 and cross-encoder
  reranking currently exist only in experimental scripts.
- **Experimental retrieval evaluation** with chunk-id-based ground truth; it is
  not yet part of the automated unit-test suite.
- **JWT auth** with a React frontend and one-command Docker startup.

---

## Architecture

```
Ingestion:  PDF / XLSX / DOCX / image
                    |  parser registry (parse_any)
                    v
              Chunk  (intermediate representation)
                    |  embed (BAAI/bge-m3, 1024-dim)
                    v
              Qdrant - single collection, payload carries tenant_id + acl_groups

Query:      question + identity (from JWT)
                    |  vector search with MANDATORY pre-filter:
                    |  tenant_id == X  AND  acl_groups intersect user_groups
                    v
              top-k context -> LLM generation -> answer + source metadata

Upload:     file -> /documents/upload -> Celery task (worker) -> parse -> embed -> index
```

The `Chunk` dataclass is the architectural centerpiece. Every parser converts its format into it;
nothing downstream knows or cares whether the source was a PDF, a spreadsheet, a Word file, or a
scanned image. `location` is polymorphic — `{type: page, num}` for PDF, `{type: cell, sheet, row}`
for spreadsheets, `{type: paragraph, index}` for Word, `{type: image, num}` for images — so each
format cites itself in its own terms without null columns.

### Versioned ingestion foundations

`eda.ingestion_schema` defines the versioned document, page, region, OCR-decision,
and provenance contracts used by adaptive PDF extraction. Internal `page_index` is
zero-based; user-facing `page_number` is one-based and must equal
`page_index + 1`. Mixed pages retain native and OCR text separately, with a
deterministic `index_text` that removes only an effectively identical duplicate.

`eda.identifiers` provides tenant-scoped logical document IDs and content-scoped
revision, page, region, and future chunk IDs. IDs are deterministic UUID5 values;
the logical document key must be an authoritative ID rather than only a filename.
Adaptive pages convert through a conservative page-sized compatibility adapter;
the legacy `Chunk` constructor remains unchanged. XLSX and adaptive PDF ingestion
require an explicit non-empty ACL scope.

---

## Tech stack

Python 3.12 · uv · FastAPI · Celery + Redis · Qdrant · sentence-transformers (bge-m3,
bge-reranker-v2-m3) · Ollama (LLM, on host) · Tesseract (OCR) · SQLite + SQLAlchemy · React +
Vite + TypeScript + Tailwind · Docker Compose.

---

## Getting started

### Prerequisites

- Docker and Docker Compose
- [Ollama](https://ollama.com) running on the host with a local model available
  (the app expects `llama3.1:8b-local`). Ollama stays outside Docker deliberately — the LLM is
  swappable and its image is heavy.
- For image OCR: Tesseract is installed inside the API/worker image automatically; no host
  install needed when running via Docker.

### Run

```bash
# 1. Start Ollama on the host, bound so containers can reach it
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# 2. Bring up the stack (Qdrant, API, frontend, Redis, Celery worker)
docker compose up -d

# 3. First-time only: index the sample tenants
docker compose run --rm api python scripts/build_index.py
```

Then open:
- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Qdrant:   http://localhost:6333

### Demo accounts

All passwords are `<username>123`.

| user   | level   | tenant          | groups        |
|--------|---------|-----------------|---------------|
| sara   | admin   | kb              | billing       |
| reza   | admin   | kb              | security      |
| ali    | user    | postgres        | engineering   |
| maryam | user    | postgres        | hr            |
| dana   | user    | acme-internal   | sales         |

`sara` and `reza` are the key pair — same tenant, different groups. Ask both the same billing
question and watch the sources diverge.

---

## Isolation, proven

Filtering is a hard constraint on the query, executed inside the vector engine:

```python
Filter(must=[
    FieldCondition(key="tenant_id",  match=MatchValue(value=tenant_id)),
    FieldCondition(key="acl_groups", match=MatchAny(any=user_groups)),
])
```

Because it runs inside the search rather than around it, no prompt content can influence it —
prompt injection has no surface to attack.

**Adversarial leak suite** — 20 queries across tenants, including exfiltration attempts and prompt
injection:

| Configuration                     | Cross-tenant leaks |
|-----------------------------------|--------------------|
| Pre-filtering enabled             | **0 / 20**         |
| Pre-filtering disabled (control)  | **20 / 20**        |

The control row is the point: a passing test proves nothing unless it can also fail. Running the
control also exposed a bug in the test itself — a tenant was named `acme` while the index used
`acme-internal`, so half the queries had silently been testing a nonexistent tenant.

---

## Experimental retrieval quality

The figures below came from the standalone `scripts/eval.py` experiment. The
production `/ask` endpoint remains dense-only, and these figures are not a current
CI-backed baseline.

Evaluated with chunk-id-based ground truth (stable across re-indexing, unlike integer point IDs):

| Configuration                      | recall@1 | recall@5 |
|------------------------------------|----------|----------|
| embedding + rerank                 | 0.75     | 0.92     |
| hybrid (BM25 + embedding) + rerank | 0.83     | 0.92     |

On this keyword-heavy set, hybrid improved recall@1 — the gain concentrated on exact-term queries
(e.g. "dollar signs" -> the dollar-quoting section) where BM25's lexical match rescues a result
dense retrieval ranks lower. On an earlier, cleaner corpus hybrid showed **no** gain; reporting
both is the honest result. Knowing when a technique doesn't earn its complexity is as useful as
knowing when it does.

---

## Two authorization systems

Kept deliberately separate — conflating them breaks both:

| System | Controls | Mechanism |
|--------|----------|-----------|
| **ACL**  | which documents a user retrieves | `tenant_id` + `acl_groups`, pre-filtered in Qdrant |
| **RBAC** | which features a user can invoke | `level` (creator/admin/user) + dynamic roles/permissions |

A user can be an admin (RBAC) who only reads billing documents (ACL). Identity for both always
comes from the JWT, never the request body — accepting it from the body would be a
privilege-escalation hole.

---

## Multi-format ingestion

A parser registry maps extension to parser:

```python
PARSERS = {".pdf": parse_pdf, ".xlsx": parse_xlsx, ".docx": parse_docx,
           ".png": parse_image, ".jpg": parse_image, ".jpeg": parse_image}
```

Adding a format is one parser plus one line — proven with Word, which uploaded through the UI
without touching the queue, endpoint, or frontend. Uploaded documents are stamped with the
uploader's tenant and groups, and their chunk IDs are namespaced by tenant so two tenants
uploading a same-named file never collide.

### Adaptive PDF extraction

PDF ingestion defaults to the existing native-text parser. Adaptive extraction
must be enabled explicitly with `EDA_PDF_EXTRACTION_MODE=adaptive` or the
`parse_pdf(..., extraction_mode="adaptive")` argument. Invalid values fail.
Adaptive callers must also provide an authoritative `logical_document_key` and
ACL groups; uploaded PDFs use their generated storage-object name as that key.

Adaptive mode requires Tesseract 5 with `fas` and `eng` language packs. Set
`TESSERACT_CMD` only when Tesseract is not on `PATH`. Initial supported profiles
are `fas+eng`, `fas`, and `eng`. `AdaptiveOCRConfig` centralizes render DPI,
bounded PSM/preprocessing candidates, timeouts, region advantage, and provisional
quality thresholds. These defaults are operational starting points, not a
scientifically validated accuracy baseline.

The adaptive pipeline emits typed `DocumentManifest` and `PageResult` objects.
Mixed pages keep native and OCR layers separately and are marked `needs_review`
because coordinate-level merging is not implemented. Table-like content remains
text regions; structured table extraction and section-aware structural chunking
remain later work.

### Canonical route-based ingestion (opt-in)

The Celery worker can ingest through the new canonical, route-based extraction
pipeline instead of the legacy parser, selected by environment variable:

- `INGESTION_PIPELINE=legacy` (default) — `parse_any` → `ingest_chunks`, unchanged.
- `INGESTION_PIPELINE=canonical` — route → canonical extraction → quality gate →
  structure-aware chunking; only accepted content is embedded, and the job result
  carries route/quality/page-verdict details.
- `INGESTION_PIPELINE=docling_first` — canonical, preferring Docling for PDF/DOCX.

Related knobs: `INGESTION_ALLOW_NEEDS_REVIEW` (default `false`),
`INGESTION_MAX_CHUNK_WORDS` (default `350`), `INGESTION_FAIL_ON_ZERO_CHUNKS`
(default `true`). `needs_review` documents are parsed but **not** indexed by
default (returned as a business outcome, not a crash). Rollback is instant:
`INGESTION_PIPELINE=legacy`. See `docs/document-ingestion-architecture.md`.

---

## Project layout

```
src/eda/        pipeline library (framework-agnostic - no FastAPI imports)
  schema.py     Chunk - the intermediate representation
  ingestion_schema.py  versioned document/page/OCR/provenance contracts
  identifiers.py       deterministic ingestion identifiers and file hashing
  evaluation_schema.py committed-sanitized/local-private fixture manifests
  ocr_routing.py       pure routing policy used by contract tests
  pdf_analysis.py      page evidence collection and classification
  ocr_quality.py       candidate metrics, quality gate and deterministic selection
  adaptive_ocr.py      typed page-level adaptive PDF extraction
  ingestion_adapter.py typed PageResult to legacy page-sized Chunk adapter
  ocr_evaluation.py    CER/WER and routing/extraction metrics
  parse.py      parsers + parse_any registry
  normalize.py  Unicode normalization + persian_ratio
  chunk.py      chunking strategies
  index.py      ingest_chunks(), lazy model singleton, uuid5 point IDs
api/            FastAPI service - auth, RAG, admin, documents, Celery tasks
scripts/        build_index.py, search.py, eval.py, leak_test.py
frontend/       React app
data/           (gitignored) Qdrant storage, SQLite DB, uploads, source files
```

OCR evaluation has two tiers under `evaluation/ocr/`: small approved
`committed_sanitized` fixtures for CI, and ignored `local_private` fixtures for
real documents. No real OCR accuracy baseline is claimed until labeled fixtures
are approved.

Run isolated tests without external services or OCR binaries:

```bash
uv run --group dev pytest
```

Run the explicitly opted-in local OCR diagnostic tests only when Tesseract and
an approved private fixture are configured:

```bash
EDA_RUN_OCR_INTEGRATION=1 EDA_PRIVATE_OCR_PDF=/local/private.pdf \
  uv run --group dev pytest -m ocr_integration
```

The typed diagnostic CLI accepts one-based pages and prints only compact metrics:

```bash
uv run python scripts/adaptive_pdf_extract.py document.pdf --pages 4,12 \
  --tenant-id local-diagnostic --logical-document-key approved-local-document
```

`eda.ocr_evaluation.normalized_cer()` and `normalized_wer()` return unavailable
when approved ground truth is absent; OCR output is never treated as truth.

---

## Notes on Persian text

The corpus surfaced findings that would have silently corrupted retrieval:

- **Two Unicode families** — standard Arabic block vs. deprecated Presentation Forms. Visually
  identical, byte-wise unrelated; NFKC + character folding collapses them. A ratio metric computed
  *before* normalization nearly discarded a third of the corpus as non-Persian.
- **Unrecoverable ligature reordering** — the lam-alef ligature extracts transposed and can't be
  repaired at the source; the fix applies the same transformation to queries, preserving lexical
  match by symmetry.
- **Language is per-chunk, not per-tenant** — a single file mixes Persian and English, so detection
  runs on each chunk.

---

## Known limitations / roadmap

- `SECRET_KEY` should come from the environment in all deployments.
- Permissions are baked into the JWT — a revoked permission stays live until token expiry (60m).
- Persian OCR quality is basic.
- Word chunking is fixed-size; structural (heading-based) chunking would keep language and section
  boundaries clean.
- Hybrid retrieval and reranking are still experimental and are outside the adaptive OCR milestone.

---

## License

See `LICENSE`.
