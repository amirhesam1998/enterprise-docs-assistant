import pytest
from pydantic import ValidationError

from eda.ingestion_schema import ExtractionRoute, OCRDecision, PageType, ProcessingStatus
from eda.ocr_routing import choose_extraction_route


def test_single_candidate_has_null_agreement_not_fake_consensus():
    decision = OCRDecision(
        selected_route=ExtractionRoute.FULL_PAGE_OCR,
        quality_gate_passed=True,
        candidate_count=1,
        agreement_score=None,
    )
    assert decision.agreement_score is None
    with pytest.raises(ValidationError):
        OCRDecision(**{**decision.model_dump(), "agreement_score": 100})


def test_synthetic_mixed_layers_route_to_combined():
    result = choose_extraction_route(
        page_type=PageType.MIXED,
        native_text="synthetic native",
        ocr_text="synthetic OCR",
        ocr_quality_gate_passed=True,
        preferred_ocr_route=ExtractionRoute.REGION_OCR,
    )
    assert result.selected_route == ExtractionRoute.COMBINED
    assert result.processing_status == ProcessingStatus.ACCEPTED


def test_synthetic_failed_ocr_is_never_accepted():
    result = choose_extraction_route(
        page_type=PageType.SCANNED,
        native_text="",
        ocr_text="uncertain OCR",
        ocr_quality_gate_passed=False,
    )
    assert result.selected_route == ExtractionRoute.REJECTED
    assert result.processing_status == ProcessingStatus.NEEDS_REVIEW
    assert result.quality_gate_passed is False


def test_synthetic_mixed_failed_ocr_retains_native_for_review():
    result = choose_extraction_route(
        page_type=PageType.MIXED,
        native_text="synthetic native",
        ocr_text="uncertain OCR",
        ocr_quality_gate_passed=False,
    )
    assert result.selected_route == ExtractionRoute.NATIVE
    assert result.processing_status == ProcessingStatus.NEEDS_REVIEW


def test_synthetic_empty_page_fails_deterministically():
    result = choose_extraction_route(
        page_type=PageType.EMPTY,
        native_text="",
        ocr_text="",
        ocr_quality_gate_passed=False,
    )
    assert result == choose_extraction_route(
        page_type=PageType.EMPTY,
        native_text="",
        ocr_text="",
        ocr_quality_gate_passed=False,
    )
    assert result.processing_status == ProcessingStatus.FAILED
