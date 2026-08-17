# Document parsing benchmark corpus

This folder holds the benchmark corpus for the **ingestion / parsing / extraction**
pipeline. The full plan — objectives, corpus design, stages, ground-truth levels,
metrics, and acceptance criteria — is in
[`docs/benchmark-corpus-plan.md`](../../docs/benchmark-corpus-plan.md).

> The repository's sample PDFs are random test files and are **not** benchmark
> evidence. No real documents are committed here.

## Layout

```
manifest.example.json     committed, synthetic — copy for a real manifest
labels/
  page_labels.example.json         committed, synthetic (Level 2)
  text_ground_truth.example.json   committed, synthetic (Level 3)
  table_ground_truth.example.json  committed, synthetic (Level 4)
local-private/            GIT-IGNORED — real/private documents live here
raw-private/              GIT-IGNORED — unsanitized originals
public-sample/            committed — optional sanitized/public documents
reports/                  generated reports (git-ignored except this README)
```

`local-private/` and `raw-private/` are git-ignored (see repo `.gitignore`) and
are created on demand — put real documents there. They are intentionally empty in
version control.

## Quick start

```bash
# 1) drop documents into evaluation/corpus/local-private/ (git-ignored)
# 2) run the extraction report per pipeline policy
uv run python scripts/extraction_report.py evaluation/corpus/local-private \
  --json > evaluation/corpus/reports/canonical.json
uv run python scripts/extraction_report.py evaluation/corpus/local-private \
  --prefer-docling --json > evaluation/corpus/reports/docling_first.json

# 3) compare
uv run python scripts/compare_extraction_reports.py \
  canonical=evaluation/corpus/reports/canonical.json \
  docling_first=evaluation/corpus/reports/docling_first.json
```

See the plan's §I (Operating workflow) for the full loop, and §G for privacy rules
(sanitize; commit only metadata and aggregate reports, never document bodies).
