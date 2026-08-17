from __future__ import annotations

from eda.ingestion_schema import ExtractionRoute
from eda.ocr_quality import OCRCandidate, QualityGatePolicy, select_candidate


GOOD_TEXT = "سند سازمانی معتبر شامل اطلاعات دقیق و چند واژه متفاوت برای آزمون استخراج است"


def candidate(route, confidence, text=GOOD_TEXT):
    return OCRCandidate(
        route=route,
        text=text,
        mean_confidence=confidence,
        psm=6,
        language_profile="fas+eng",
        preprocessing="original",
        word_count=10,
        coverage=0.03,
    )


def test_candidate_order_does_not_change_selection():
    candidates = [
        candidate(ExtractionRoute.REGION_OCR, 80),
        candidate(ExtractionRoute.FULL_PAGE_OCR, 92),
        candidate(ExtractionRoute.FULL_PAGE_OCR, 85),
    ]
    first = select_candidate(candidates, policy=QualityGatePolicy(), region_min_advantage=5)
    second = select_candidate(list(reversed(candidates)), policy=QualityGatePolicy(), region_min_advantage=5)
    assert first.selected == second.selected


def test_lower_scoring_region_cannot_win_for_complex_layout():
    result = select_candidate(
        [
            candidate(ExtractionRoute.REGION_OCR, 75),
            candidate(ExtractionRoute.FULL_PAGE_OCR, 95),
        ],
        policy=QualityGatePolicy(),
        region_min_advantage=0,
    )
    assert result.selected.route == ExtractionRoute.FULL_PAGE_OCR


def test_region_candidate_requires_configured_advantage():
    candidates = [
        candidate(ExtractionRoute.FULL_PAGE_OCR, 82),
        candidate(ExtractionRoute.REGION_OCR, 90),
    ]
    strict = select_candidate(candidates, policy=QualityGatePolicy(), region_min_advantage=20)
    permissive = select_candidate(candidates, policy=QualityGatePolicy(), region_min_advantage=1)
    assert strict.selected.route == ExtractionRoute.FULL_PAGE_OCR
    assert permissive.selected.route == ExtractionRoute.REGION_OCR


def test_quality_gate_rejects_low_confidence_candidate():
    result = select_candidate(
        [candidate(ExtractionRoute.FULL_PAGE_OCR, 10)],
        policy=QualityGatePolicy(),
        region_min_advantage=5,
    )
    assert result.selected is None
    assert "ocr_confidence_below_threshold" in result.candidates[0].rejection_reasons


def test_empty_candidate_is_recorded_and_rejected():
    result = select_candidate(
        [candidate(ExtractionRoute.FULL_PAGE_OCR, 95, text="")],
        policy=QualityGatePolicy(),
        region_min_advantage=5,
    )
    assert result.selected is None
    assert result.candidates[0].quality_gate_passed is False
    assert "ocr_text_too_short" in result.candidates[0].rejection_reasons


def test_single_candidate_agreement_is_null():
    result = select_candidate(
        [candidate(ExtractionRoute.FULL_PAGE_OCR, 95)],
        policy=QualityGatePolicy(),
        region_min_advantage=5,
    )
    assert result.selected.agreement_score is None
