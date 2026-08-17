"""CLI: compare several extraction-report JSON files side by side.

Each input is the JSON emitted by ``scripts/extraction_report.py --json`` (an
object ``{"reports": [...], "summary": {...}}``) or a bare list of report rows.
Label each file so the comparison rows are named — typically by pipeline policy:

    uv run python scripts/compare_extraction_reports.py \
        canonical=evaluation/corpus/reports/canonical.json \
        docling_first=evaluation/corpus/reports/docling_first.json

A bare path (no ``label=``) is labeled by its filename stem. The tool only reads
already-generated reports; it never runs extraction and needs no documents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _rows(payload) -> list[dict]:
    """Accept either the CLI object shape or a bare list of report rows."""
    if isinstance(payload, dict):
        return list(payload.get("reports", []))
    if isinstance(payload, list):
        return list(payload)
    raise ValueError("Report JSON must be an object with 'reports' or a list of rows.")


def summarize_report(payload, label: str) -> dict:
    """Aggregate one report into comparable per-pipeline totals."""
    rows = _rows(payload)
    extracted = [row for row in rows if "error" not in row]

    def total(key: str) -> int:
        return sum(int(row.get(key, 0) or 0) for row in extracted)

    scores = [row.get("average_quality_score") for row in extracted if row.get("average_quality_score") is not None]
    warning_count = sum(len(row.get("warnings", []) or []) for row in extracted)
    # Extraction-level failures (rows carrying an "error") count as errors too.
    error_count = sum(len(row.get("errors", []) or []) for row in extracted) + (len(rows) - len(extracted))

    return {
        "pipeline": label,
        "files": len(rows),
        "avg_quality_score": round(sum(scores) / len(scores), 2) if scores else None,
        "accepted_pages": total("accepted_pages"),
        "needs_review_pages": total("needs_review_pages"),
        "failed_pages": total("failed_pages"),
        "table_count": total("table_count"),
        "warning_count": warning_count,
        "error_count": error_count,
    }


_COLUMNS = [
    ("pipeline", "pipeline"),
    ("files", "files"),
    ("avg_quality_score", "avg_q"),
    ("accepted_pages", "accepted"),
    ("needs_review_pages", "review"),
    ("failed_pages", "failed"),
    ("table_count", "tables"),
    ("warning_count", "warns"),
    ("error_count", "errors"),
]


def format_comparison(summaries: list[dict]) -> str:
    """Render summaries as a fixed-width comparison table."""
    header = [label for _key, label in _COLUMNS]
    rows = [header]
    for summary in summaries:
        rows.append([
            "-" if summary.get(key) is None else str(summary.get(key))
            for key, _label in _COLUMNS
        ])
    widths = [max(len(row[col]) for row in rows) for col in range(len(header))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)))
        if index == 0:
            lines.append("  ".join("-" * widths[col] for col in range(len(header))))
    return "\n".join(lines)


def _parse_input(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        label, _, path = spec.partition("=")
        return label or Path(path).stem, Path(path)
    path = Path(spec)
    return path.stem, path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare extraction-report JSON files.")
    parser.add_argument(
        "inputs", nargs="+", metavar="[LABEL=]REPORT.json",
        help="One or more report files; prefix with LABEL= to name the row.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args()

    summaries = []
    for spec in args.inputs:
        label, path = _parse_input(spec)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"error: could not read {path.name}: {error}", file=sys.stderr)
            return 1
        summaries.append(summarize_report(payload, label))

    if args.json:
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
    else:
        print(format_comparison(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
