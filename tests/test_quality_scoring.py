from __future__ import annotations

from eda.ingestion_schema import (
    ExtractionRoute,
    OCRDecision,
    PageType,
    ProcessingStatus,
)
from eda.quality import (
    DEFAULT_THRESHOLDS,
    QualityLevel,
    level_for_score,
    score_document,
    score_page,
    score_text,
    to_processing_status,
)

GARBAGE = "�□■ ]{}|~ ▪ �� ◆◆ ][}{ �"
ENGLISH = (
    "The quarterly financial report shows that revenue increased by twelve "
    "percent compared with the prior fiscal year across all regions."
)
PERSIAN = (
    "گزارش مالی سه ماهه نشان می‌دهد که درآمد نسبت به سال گذشته دوازده درصد "
    "افزایش یافته و هزینه‌های عملیاتی کاهش پیدا کرده است."
)


def test_garbage_text_scores_in_failed_band():
    score = score_text(GARBAGE)
    assert score < DEFAULT_THRESHOLDS.needs_review
    assert level_for_score(score) == QualityLevel.FAILED


def test_normal_bilingual_text_is_acceptable():
    for text in (ENGLISH, PERSIAN):
        assert score_text(text) >= DEFAULT_THRESHOLDS.accepted_with_warning


def test_level_thresholds_are_ordered():
    assert level_for_score(95) == QualityLevel.ACCEPTED
    assert level_for_score(80) == QualityLevel.ACCEPTED_WITH_WARNING
    assert level_for_score(55) == QualityLevel.NEEDS_REVIEW
    assert level_for_score(10) == QualityLevel.FAILED
    assert to_processing_status(QualityLevel.ACCEPTED_WITH_WARNING) == ProcessingStatus.ACCEPTED
    assert to_processing_status(QualityLevel.NEEDS_REVIEW) == ProcessingStatus.NEEDS_REVIEW


def test_high_text_score_cannot_upgrade_a_needs_review_page(page_factory):
    # A page the pipeline flagged for review keeps that ceiling even with clean text.
    page = page_factory(
        native_text=ENGLISH,
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.NATIVE,
            quality_gate_passed=False,
            candidate_count=0,
        ),
    )
    pq = score_page(page)
    assert pq.score >= DEFAULT_THRESHOLDS.accepted_with_warning  # text itself is clean
    assert pq.level == QualityLevel.NEEDS_REVIEW
    assert pq.status == ProcessingStatus.NEEDS_REVIEW


def test_accepted_clean_page_scores_accepted(page_factory):
    pq = score_page(page_factory(native_text=ENGLISH))
    assert pq.status == ProcessingStatus.ACCEPTED
    assert pq.level in {QualityLevel.ACCEPTED, QualityLevel.ACCEPTED_WITH_WARNING}


def test_document_with_no_accepted_page_is_not_accepted(page_factory):
    failed = page_factory(
        native_text="",
        processing_status=ProcessingStatus.FAILED,
        page_type=PageType.EMPTY,
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.REJECTED,
            quality_gate_passed=False,
            candidate_count=0,
        ),
    )
    report = score_document("doc", [failed])
    assert report.accepted_pages == 0
    assert report.level in {QualityLevel.NEEDS_REVIEW, QualityLevel.FAILED}
