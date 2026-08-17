"""CLI: run the extraction quality report over a folder of documents.

Usage (from the project root):

    uv run python scripts/extraction_report.py data/benchmark
    uv run python scripts/extraction_report.py data/benchmark --prefer-docling --json

It reports only measured extraction signals. Do NOT read the numbers on the
repo's random sample PDFs as a quality benchmark — point it at real Persian /
English enterprise documents once such a corpus is available locally.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eda.extraction_report import aggregate, run_folder  # noqa: E402
from eda.extractors.router import default_router, docling_first_router  # noqa: E402


def _format_table(reports: list[dict]) -> str:
    headers = ["file", "route", "pages", "ok", "review", "fail", "avg", "tables", "ocr"]
    rows = [headers]
    for report in reports:
        if "error" in report:
            rows.append([report["file"], "ERROR", "-", "-", "-", "-", "-", "-", "-"])
            continue
        rows.append([
            report["file"],
            report["extractor_route"],
            str(report["page_count"]),
            str(report["accepted_pages"]),
            str(report["needs_review_pages"]),
            str(report["failed_pages"]),
            f"{report['average_quality_score']:.1f}",
            str(report["table_count"]),
            str(report["ocr_route_pages"]),
        ])
    widths = [max(len(row[col]) for row in rows) for col in range(len(headers))]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(row)))
        if index == 0:
            lines.append("  ".join("-" * widths[col] for col in range(len(headers))))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extraction quality report over a folder.")
    parser.add_argument("folder", help="Directory of documents to report on.")
    parser.add_argument("--prefer-docling", action="store_true", help="Lead with Docling for PDF/DOCX.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument("--acl", default="evaluation", help="ACL group for XLSX extraction (default: evaluation).")
    args = parser.parse_args()

    router = docling_first_router() if args.prefer_docling else default_router()
    reports = run_folder(args.folder, router=router, acl_groups=(args.acl,))
    summary = aggregate(reports)

    if args.json:
        print(json.dumps({"reports": reports, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        if reports:
            print(_format_table(reports))
        else:
            print("No supported documents found.")
        print()
        print("Summary:", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
