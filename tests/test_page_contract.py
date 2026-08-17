from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from eda.ingestion_schema import (
    ExtractionRoute,
    OCRDecision,
    PageType,
    ProcessingStatus,
)


def combined_decision(**overrides) -> OCRDecision:
    values = {
        "mean_confidence": 80,
        "quality_score": 80,
        "agreement_score": 75,
        "selection_score": 79,
        "selected_route": ExtractionRoute.COMBINED,
        "selected_psm": "mixed",
        "selected_language_profile": "fas+eng",
        "selected_preprocessing": "mixed",
        "quality_gate_passed": True,
        "candidate_count": 2,
        "processing_time_ms": 10,
    }
    values.update(overrides)
    return OCRDecision(**values)


def test_page_number_must_match_zero_based_index(page_factory):
    with pytest.raises(ValidationError):
        page_factory(page_index=1, page_number=1)


def test_page_id_must_match_revision_and_index(page_factory):
    with pytest.raises(ValidationError):
        page_factory(page_index=1, page_number=2)


def test_mixed_page_preserves_both_layers(page_factory):
    page = page_factory(
        page_type=PageType.MIXED,
        native_text="native layer",
        ocr_text="ocr layer",
        ocr_decision=combined_decision(),
    )
    assert page.native_text == "native layer"
    assert page.ocr_text == "ocr layer"
    assert page.index_text == "native layer\n\nocr layer"


def test_effectively_identical_layers_are_not_duplicated(page_factory):
    page = page_factory(
        page_type=PageType.MIXED,
        native_text="Same   text",
        ocr_text=" same text ",
        ocr_decision=combined_decision(),
    )
    assert page.index_text == "Same   text"


def test_rejected_or_failed_gate_cannot_be_accepted(page_factory):
    rejected = OCRDecision(
        selected_route=ExtractionRoute.REJECTED,
        quality_gate_passed=False,
        candidate_count=1,
    )
    with pytest.raises(ValidationError):
        page_factory(
            processing_status=ProcessingStatus.ACCEPTED,
            native_text="",
            ocr_text="rejected OCR",
            ocr_decision=rejected,
        )

    failed_gate = combined_decision(quality_gate_passed=False)
    with pytest.raises(ValidationError):
        page_factory(
            page_type=PageType.MIXED,
            native_text="native",
            ocr_text="uncertain OCR",
            ocr_decision=failed_gate,
        )


def test_uncertain_output_can_be_marked_needs_review(page_factory):
    page = page_factory(
        page_type=PageType.MIXED,
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        native_text="native",
        ocr_text="uncertain OCR",
        ocr_decision=combined_decision(quality_gate_passed=False),
    )
    assert page.processing_status == ProcessingStatus.NEEDS_REVIEW


def test_empty_accepted_page_is_rejected(page_factory):
    with pytest.raises(ValidationError):
        page_factory(
            native_text="",
            ocr_text="",
            ocr_decision=OCRDecision(
                selected_route=ExtractionRoute.REJECTED,
                quality_gate_passed=False,
                candidate_count=0,
            ),
        )


def test_deterministic_payload_excludes_runtime_fields(page_factory, provenance):
    first = page_factory(
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.NATIVE,
            quality_gate_passed=True,
            candidate_count=0,
            processing_time_ms=1,
        )
    )
    later = provenance.model_copy(
        update={"processing_timestamp": datetime(2027, 1, 1, tzinfo=timezone.utc)}
    )
    second = page_factory(
        provenance=later,
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.NATIVE,
            quality_gate_passed=True,
            candidate_count=0,
            processing_time_ms=999,
        ),
    )
    assert first.deterministic_payload() == second.deterministic_payload()
