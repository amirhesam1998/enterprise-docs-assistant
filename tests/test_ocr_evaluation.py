from __future__ import annotations

import pytest

from eda.ocr_evaluation import (
    extraction_coverage,
    failure_rate,
    normalize_persian_for_evaluation,
    normalized_cer,
    normalized_wer,
    page_classification_accuracy,
    processing_duration_report,
    route_accuracy,
)


def test_persian_normalization_handles_arabic_variants_and_whitespace():
    assert normalize_persian_for_evaluation("  يكي\u200cك  ") == "یکی ک"


def test_cer_and_wer_use_supplied_ground_truth():
    assert normalized_cer("سلام دنی", "سلام دنیا") == pytest.approx(1 / 9)
    assert normalized_wer("سلام دنی", "سلام دنیا") == pytest.approx(0.5)


def test_missing_ground_truth_is_unavailable_not_zero():
    assert normalized_cer("OCR output", None) is None
    assert normalized_wer("OCR output", None) is None


def test_route_classification_coverage_failure_and_duration_metrics():
    assert route_accuracy(["native", "rejected"], ["native", "full_page_ocr"]) == 0.5
    assert page_classification_accuracy(["digital"], ["digital"]) == 1.0
    assert extraction_coverage(3, 4) == 0.75
    assert failure_rate(1, 4) == 0.25
    report = processing_duration_report([10, 20, 30])
    assert (report.count, report.total_ms, report.mean_ms, report.median_ms, report.maximum_ms) == (
        3,
        60,
        20,
        20,
        30,
    )

