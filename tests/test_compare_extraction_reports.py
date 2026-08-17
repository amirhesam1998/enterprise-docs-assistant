"""Unit tests for the report-comparison helper. Synthetic JSON only — no docs."""

from __future__ import annotations

from scripts.compare_extraction_reports import (
    format_comparison,
    summarize_report,
)

# Mirrors scripts/extraction_report.py --json output for two files, one of which
# failed extraction (carries an "error" key instead of the usual metrics).
CANONICAL = {
    "reports": [
        {
            "file": "a.pdf", "extractor_route": "native_pdf", "page_count": 3,
            "accepted_pages": 3, "needs_review_pages": 0, "failed_pages": 0,
            "empty_pages": 0, "average_quality_score": 90.0, "quality_level": "accepted",
            "table_count": 1, "ocr_route_pages": 0, "warnings": [], "errors": [],
        },
        {
            "file": "b.pdf", "extractor_route": "adaptive_pdf_ocr", "page_count": 2,
            "accepted_pages": 1, "needs_review_pages": 1, "failed_pages": 0,
            "empty_pages": 0, "average_quality_score": 60.0, "quality_level": "needs_review",
            "table_count": 0, "ocr_route_pages": 2, "warnings": ["native_pdf_insufficient_output"],
            "errors": [],
        },
        {"file": "c.pdf", "extractor_route": None, "error": "No extractor produced usable output."},
    ],
    "summary": {"files": 3},
}


def test_summarize_report_aggregates_totals():
    summary = summarize_report(CANONICAL, "canonical")
    assert summary["pipeline"] == "canonical"
    assert summary["files"] == 3
    assert summary["accepted_pages"] == 4
    assert summary["needs_review_pages"] == 1
    assert summary["failed_pages"] == 0
    assert summary["table_count"] == 1
    assert summary["avg_quality_score"] == 75.0  # mean of 90 and 60 (failed row excluded)
    assert summary["warning_count"] == 1
    assert summary["error_count"] == 1  # the extraction-level failure on c.pdf


def test_summarize_accepts_bare_list():
    rows = CANONICAL["reports"]
    assert summarize_report(rows, "x")["files"] == 3


def test_empty_report_has_no_average():
    summary = summarize_report({"reports": []}, "empty")
    assert summary["files"] == 0
    assert summary["avg_quality_score"] is None


def test_format_comparison_includes_labels_and_header():
    table = format_comparison([
        summarize_report(CANONICAL, "canonical"),
        summarize_report({"reports": []}, "docling_first"),
    ])
    assert "pipeline" in table
    assert "canonical" in table
    assert "docling_first" in table
