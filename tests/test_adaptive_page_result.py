from __future__ import annotations

from dataclasses import replace

from eda.adaptive_ocr import AdaptiveOCRConfig, CandidateBatch, build_page_result
from eda.ingestion_schema import ExtractionRoute, PageType, ProcessingStatus
from eda.ocr_quality import OCRCandidate
from eda.pdf_analysis import NativeTextBlock, PageEvidence, classify_page


NATIVE = "متن بومی معتبر سند شامل چندین واژه روشن و اطلاعات سازمانی قابل استفاده است"
OCR = "متن OCR متفاوت شامل اطلاعات تکمیلی تصویر و چندین واژه قابل استفاده است"


def evidence(native=NATIVE, image_coverage=0.5, visual=0.08, blocks=True):
    compact = "".join(native.split())
    return PageEvidence(
        native_text=native,
        normalized_native_characters=len(compact),
        meaningful_character_ratio=(sum(char.isalnum() for char in compact) / len(compact)) if compact else 0,
        image_coverage=image_coverage,
        visual_content_ratio=visual,
        native_blocks=(NativeTextBlock((10, 10, 500, 100), native),) if native and blocks else (),
        page_width_points=600,
        page_height_points=800,
        rendered_width_pixels=1200,
        rendered_height_pixels=1600,
    )


def candidate(text=OCR, confidence=92):
    return OCRCandidate(
        route=ExtractionRoute.FULL_PAGE_OCR,
        text=text,
        mean_confidence=confidence,
        psm=6,
        language_profile="fas+eng",
        preprocessing="original",
        word_count=12,
        coverage=0.03,
    )


def build(identity, provenance, source_evidence, candidates):
    config = AdaptiveOCRConfig()
    preliminary = classify_page(source_evidence, policy=config.classification)
    return build_page_result(
        evidence=source_evidence,
        preliminary_classification=preliminary,
        candidate_batch=CandidateBatch(tuple(candidates)),
        config=config,
        document_id=identity["document_id"],
        revision_id=identity["revision_id"],
        page_index=0,
        provenance=provenance,
        processing_time_ms=1,
    )


def test_mixed_distinct_layers_are_preserved_for_review(identity, provenance):
    page = build(identity, provenance, evidence(), [candidate()])
    repeated = build(identity, provenance, evidence(), [candidate()])
    assert page.page_type == PageType.MIXED
    assert page.processing_status == ProcessingStatus.NEEDS_REVIEW
    assert page.ocr_decision.selected_route == ExtractionRoute.COMBINED
    assert page.native_text == NATIVE and page.ocr_text == OCR
    assert page.index_text == f"{NATIVE}\n\n{OCR}"
    assert [region.region_id for region in page.regions] == [
        region.region_id for region in repeated.regions
    ]
    assert "text" not in page.ocr_decision.candidate_metrics[0].model_dump()


def test_effectively_identical_mixed_layers_are_not_duplicated(identity, provenance):
    arabic_variant = NATIVE.replace("ی", "ي").replace("ک", "ك")
    page = build(identity, provenance, evidence(), [candidate(arabic_variant)])
    assert page.native_text and page.ocr_text
    assert page.index_text == NATIVE


def test_partially_overlapping_layers_remain_distinct(identity, provenance):
    page = build(identity, provenance, evidence(), [candidate("اطلاعات سازمانی و پیوست تصویری جدید قابل استفاده است")])
    assert page.index_text.startswith(NATIVE)
    assert "پیوست تصویری" in page.index_text


def test_failed_ocr_retains_usable_native_text(identity, provenance):
    page = build(identity, provenance, evidence(), [candidate("خراب", confidence=5)])
    assert page.processing_status == ProcessingStatus.NEEDS_REVIEW
    assert page.ocr_decision.selected_route == ExtractionRoute.NATIVE
    assert page.native_text == NATIVE
    assert page.ocr_text == "خراب"
    assert page.ocr_decision.quality_gate_passed is False


def test_unusable_native_with_good_ocr_uses_ocr_and_preserves_native(identity, provenance):
    page = build(identity, provenance, evidence(native="x", blocks=False), [candidate()])
    assert page.processing_status == ProcessingStatus.ACCEPTED
    assert page.ocr_decision.selected_route == ExtractionRoute.FULL_PAGE_OCR
    assert page.native_text == "x" and page.ocr_text == OCR


def test_both_layers_unusable_fail(identity, provenance):
    page = build(identity, provenance, evidence(native="", image_coverage=0, visual=0, blocks=False), [])
    assert page.processing_status == ProcessingStatus.FAILED
    assert page.ocr_decision.selected_route == ExtractionRoute.REJECTED
    assert not page.index_text
