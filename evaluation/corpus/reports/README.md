# Generated extraction reports

Reports written here by `scripts/extraction_report.py` (and comparisons from
`scripts/compare_extraction_reports.py`) are **git-ignored** (`*.json`, `*.csv`,
`*.html`) — only this README is committed. Reports may summarize the content of
private documents, so they are treated as private artifacts.

Example:

```bash
uv run python scripts/extraction_report.py evaluation/corpus/local-private \
  --json > evaluation/corpus/reports/canonical.json
```
