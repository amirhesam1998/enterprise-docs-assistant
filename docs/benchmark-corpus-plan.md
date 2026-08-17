# Benchmark corpus plan & evaluation protocol

Status: **plan only.** This document describes the corpus we eventually need, how
to label it, how to score extraction, and how to decide whether the parser is good
enough. It does **not** report results, does **not** tune thresholds, and does
**not** add real documents. The repository's existing sample PDFs are random test
files and are explicitly **not** benchmark evidence.

Companion: [`document-ingestion-architecture.md`](./document-ingestion-architecture.md).

---

## A. Objective

**What this benchmark is for.** Measuring the *ingestion / parsing / extraction*
quality of the pipeline in `src/eda/extractors/`, `src/eda/quality.py`, and
`src/eda/structure_chunker.py` on realistic Persian and English enterprise
documents. Concretely it answers:

- Can we extract text reliably (digital and scanned)?
- Do we preserve reading order (incl. RTL and multi-column)?
- Can we detect and parse tables?
- Do we handle Persian, English, and mixed Persian/English?
- Do we handle scanned PDFs and image-only documents?
- Do we detect low-quality extraction **before** embedding?
- Can we compare `legacy` vs `canonical` vs `docling_first`?
- Do we route documents to `accepted` / `needs_review` / `failed` correctly?

**What this benchmark is NOT (yet).**

- It is **not** a RAG answer-quality benchmark. Retrieval/answer correctness,
  citation accuracy, and LLM grounding are a later phase (Ground-truth Level 5).
- It is **not** a claim of accuracy. No "90–95%" number is asserted anywhere; the
  acceptance criteria in §F are *targets to be calibrated*, not measured results.
- It is **not** a model/embedding benchmark. bge-m3 and Ollama are out of scope.

---

## B. Corpus design

Each document is tagged along three independent axes. A single file usually
carries several tags (e.g. *scanned PDF · invoice · Persian · Persian table ·
low-contrast scan*). Tags reuse the vocabulary already in
`eda.evaluation_schema.EvaluationTag` where possible and extend it.

### Format categories
digital PDF · scanned PDF · mixed PDF (native + scanned pages) · image-only
document (PNG/JPG) · DOCX · XLSX · table-heavy PDF · form-like document ·
multi-column document · poor-quality scan · rotated/skewed scan · Persian-only ·
English-only · mixed Persian/English · Persian table · English table.

### Enterprise content categories
policy document · invoice / billing · HR document · technical manual ·
legal / contract · product / spec sheet · spreadsheet / report ·
support / operations document · form / application · meeting / report document.

### Language & layout challenge categories
RTL Persian paragraphs · Persian/English mixed lines · Persian / Arabic / Latin
digits · ZWNJ / half-space (`‌`) · Arabic-vs-Persian character variants
(`ي/ی`, `ك/ک`) · headers / footers · footnotes · tables spanning pages ·
multi-column reading order · image + text mixed pages · low-contrast scans.

**Out of scope (mark explicitly, do not collect for v1):** handwriting,
handwritten annotations, CAD/engineering drawings, dense mathematical notation,
audio/video-derived documents, and password-protected/encrypted files (the
adaptive extractor already rejects encrypted PDFs).

### Coverage matrix (target, per stage)
Aim for at least one document in **every** cell of *{Persian, English, mixed} ×
{digital, scanned, mixed, image, DOCX, XLSX}* before drawing conclusions about a
cell. A verdict for a cell with zero documents is not a verdict — it is a gap.

---

## C. Corpus size stages

| Stage | Name | Docs | Labeling effort | Purpose / what you can (and cannot) decide |
|-------|------|------|-----------------|--------------------------------------------|
| 0 | Smoke corpus | 10–15 | Level 1 only (~1h) | Synthetic or public-safe files. Verify the harness runs end-to-end and the JSON report is well-formed. **Cannot** conclude anything about quality. |
| 1 | Calibration corpus | 50–100 | Level 1–2, Level 3–4 on a subset (~1–2 days) | Balanced Persian/English/formats. Used to *set* `QualityThresholds`, OCR-gate limits, and routing preferences. Thresholds may be tuned **only** here. |
| 2 | Validation corpus | 100–300 | Level 1–2, Level 3–4 on a subset (~3–5 days) | Held out from Stage 1 (no overlap). Used to *report* extraction quality against §F. Never used for tuning. |
| 3 | Production monitoring sample | ongoing | Privacy-safe metadata + small manual-review subset weekly | Sampled real uploads. Detects drift and real-world failure modes the fixed corpus misses. Feeds new hard cases back into Stages 1–2. |

Rules: **calibrate on Stage 1, report on Stage 2.** A number produced on the same
documents used to tune the thresholds is not a validation number. Keep the split
recorded in the manifest (`label_level` + a `split` field if desired).

---

## D. Ground-truth strategy (five levels)

Full page-level ground truth for every document is expensive and **not** required
to start. Label the *cheapest useful level first* and deepen only where a metric
demands it. Every level is optional per document and recorded in the manifest.

**Level 1 — file/page metadata only** (cheapest, do for all documents)
format, language, page count, scanned/digital/mixed, has tables, has forms,
multi-column, quality challenges, expected route. → drives coverage and routing
metrics. See `manifest.example.json`.

**Level 2 — page-level extraction labels** (moderate, do for most)
per page: expected page type, `accepted` / `needs_review` / `failed` human
verdict, reading-order good/bad, rough text-coverage bucket, OCR-garbage yes/no,
table-detected yes/no. → drives page-verdict and reading-order metrics. See
`page_labels.example.json`.

**Level 3 — text ground truth** (expensive, selected pages only)
normalized expected text for chosen pages — **especially Persian OCR pages** where
CER/WER is the only trustworthy signal. Use a fixed normalization profile (see
`eda.ocr_evaluation.normalize_persian_for_evaluation`). See
`text_ground_truth.example.json`.

**Level 4 — table ground truth** (expensive, selected tables only)
expected row/column counts, header row, and a handful of sample cells per chosen
table. Full cell-by-cell truth only for a small, hard subset. See
`table_ground_truth.example.json`.

**Level 5 — retrieval / RAG labels** (future phase, out of scope now)
question → expected answer + expected citing document/page. Not part of this
ingestion benchmark.

> Guiding principle: **breadth of Level 1–2 beats depth of Level 3–4.** A wide,
> shallow label set finds routing/quality-gate bugs fast; deep text/table truth is
> spent surgically where a metric can't be computed any other way.

---

## E. Metrics

All metrics are computed from the canonical `PageResult`/`BlockResult` output plus
the labels above. Existing helpers: `eda.extraction_report` (per-file rollup),
`eda.ocr_evaluation` (CER/WER, route & page-classification accuracy, coverage,
failure rate), `eda.quality` (0–100 score + `QualityLevel`).

### Extraction metrics
document success rate · page-accepted rate · needs_review rate · failed-page rate
· **empty false-positive rate** (pages the pipeline called empty that a human says
have content) · text coverage · OCR mean confidence (where available) · garbage
ratio · repetition ratio · quality-score distribution (histogram by band).

### OCR text metrics (Level-3 pages)
CER · WER · **normalized** CER/WER for Persian (glyph/ZWNJ/digit-folded) ·
language-specific failure rate (fa vs en vs mixed).

### Layout metrics (Level-2 pages)
reading-order correctness · heading/paragraph/list-item block-type detection ·
block-count sanity (not wildly over/under-segmented) · multi-column order accuracy.

### Table metrics (Level-4 tables)
table-detection precision/recall · row-count accuracy · column-count accuracy ·
cell-text accuracy · header preservation · **table-chunk usefulness** (does the
`table_reading_text` row/column context survive into the chunk?).

### Chunking metrics
chunks per page/document · average chunk size (words) · headings carried into
their section chunk · table chunks carry row/column context · **pages skipped by
the quality gate** (must equal the failed/needs_review count — a skipped accepted
page is a bug).

### Pipeline comparison (`legacy` vs `canonical` vs `docling_first`)
route chosen · fallback counts · extraction runtime · chunk count · quality score ·
embedded chunks · warning/error counts. Produced by running each pipeline over the
same corpus and diffing the reports (see §I and `scripts/compare_extraction_reports.py`).

---

## F. Acceptance criteria (initial targets — NOT yet met)

These are **initial target gates to be calibrated on Stage 1 and reported on
Stage 2.** They are written down so the team has something to calibrate toward;
none is claimed to be achieved, and all thresholds are provisional.

- ≥ 90% page-accepted rate on the validation corpus for **digital PDF / DOCX / XLSX**.
- ≥ 85% page-accepted rate for **mixed / scanned PDF**.
- ≥ 90% table-detection recall on **table-heavy digital** documents.
- ≥ 80% cell-text accuracy on the **selected labeled tables**.
- Persian OCR **normalized CER below a chosen threshold** (TBD on Stage 1) on
  labeled OCR pages.
- **Zero** low-quality pages embedded when the quality gate says
  `needs_review`/`failed` (a hard invariant, already enforced by
  `structure_chunker`).
- **Zero** cross-tenant / ACL regression (guarded by the existing adversarial leak
  suite; re-verified whenever ingestion changes).

The last two are correctness invariants and are expected to hold now; the rate
targets are aspirations pending real data.

---

## G. Privacy & safety

- **Do not commit private documents.** Real enterprise files live only in
  git-ignored folders (`evaluation/corpus/local-private/`, `raw-private/`).
- **Sanitize where possible** — redact names, national IDs, account numbers,
  signatures — before a document leaves a local machine or is used in a shared
  report.
- **Prefer metadata + summaries over raw text.** Committed artifacts should be
  labels, manifests, and aggregate reports — never document bodies. This mirrors
  the public-metadata validators already in `eda.ingestion_schema` (no absolute
  paths, no secrets, no duplicated document text).
- **No secrets/PII in fixtures.** Synthetic examples only for anything committed.
- **Separate tiers**, matching `eda.evaluation_schema`: `committed_sanitized`
  (public/sanitized, in git) vs `local_private` (private/restricted, git-ignored).
- Generated reports under `reports/` are git-ignored except their README.

---

## H. Recommended folder structure

```
evaluation/
  corpus/
    README.md                         # committed: how to use the corpus
    manifest.example.json             # committed: synthetic example manifest
    local-private/                    # GIT-IGNORED: real/private documents
    raw-private/                      # GIT-IGNORED: unsanitized originals
    public-sample/                    # committed: optional sanitized/public docs + README
    labels/
      page_labels.example.json        # committed: synthetic examples
      text_ground_truth.example.json
      table_ground_truth.example.json
    reports/
      README.md                       # committed
      *.json / *.csv / *.html         # GIT-IGNORED: generated reports
```

The existing `evaluation/ocr/` tree (with `committed_sanitized/` and
`local_private/`) stays as-is; `evaluation/corpus/` is the broader
document-parsing corpus described here.

---

## I. Operating workflow

1. **Collect** documents into `evaluation/corpus/local-private/` (git-ignored).
   Sanitize into `public-sample/` only if they can be shared.
2. **Fill the manifest** (`manifest.example.json` as the template) — at least
   Level 1 for every file.
3. **Run the extraction report** per pipeline policy:
   ```bash
   uv run python scripts/extraction_report.py evaluation/corpus/local-private \
     --json > evaluation/corpus/reports/canonical.json
   uv run python scripts/extraction_report.py evaluation/corpus/local-private \
     --prefer-docling --json > evaluation/corpus/reports/docling_first.json
   ```
   > Note: the offline report harness runs the **router** (canonical vs
   > docling-first). The `legacy` parser path is exercised through the Celery job
   > result (`INGESTION_PIPELINE=legacy`) rather than this harness; capture that
   > payload separately if a legacy row is needed.
4. **Compare pipelines**:
   ```bash
   uv run python scripts/compare_extraction_reports.py \
     canonical=evaluation/corpus/reports/canonical.json \
     docling_first=evaluation/corpus/reports/docling_first.json
   ```
5. **Review low-score pages** — sort report rows by `average_quality_score`, open
   the worst offenders, confirm whether the low score is correct.
6. **Add labels selectively** — Level 2 for reviewed pages; Level 3/4 only where a
   metric (CER/WER, cell accuracy) requires ground truth.
7. **Tune thresholds only on the calibration corpus** (Stage 1) — never on Stage 2.
8. **Validate on the held-out corpus** (Stage 2) and report against §F.

---

## J. Interview-ready explanation

> "The sample PDFs in the repo are throwaway test files, so I refused to quote any
> accuracy off them. Instead I designed a staged benchmark: a tiny smoke corpus to
> prove the harness runs, a 50–100 doc calibration set to tune the quality
> thresholds, and a held-out 100–300 doc validation set to report on — calibrate on
> one, report on the other, never both. Documents are tagged on three axes —
> format, enterprise content type, and language/layout challenge — so I can say
> *'Persian scanned tables'* as a cell, not just *'PDFs'*. Ground truth is layered:
> cheap Level-1 metadata for everything, page verdicts for most, and expensive
> text/table truth only where a metric like Persian CER or table-cell accuracy
> can't be computed any other way. The metrics separate extraction, OCR text,
> layout, tables, and chunking, plus a pipeline comparison across legacy /
> canonical / docling_first. Acceptance criteria are written down as *targets to
> calibrate*, with two hard invariants that must hold today: no low-quality page
> gets embedded, and no cross-tenant leak. The whole thing is privacy-first —
> private docs stay in git-ignored folders and only sanitized metadata and
> aggregate reports are ever committed."

Key defensible points: **no accuracy claims without real data**, **calibrate vs.
validate split**, **layered/cheap-first labeling**, **quality gate before
embedding**, and **privacy by construction**.
