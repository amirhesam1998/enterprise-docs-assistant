"""Deterministic OCR quality gates and route selection.

Thresholds are provisional operating defaults, not validated OCR benchmarks.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from eda.ingestion_schema import ExtractionRoute, OCRCandidateMetrics


@dataclass(frozen=True)
class QualityGatePolicy:
    min_mean_confidence: float = 55.0
    min_quality_score: float = 55.0
    min_meaningful_character_ratio: float = 0.55
    max_garbage_ratio: float = 0.08
    max_repetition_ratio: float = 0.75
    min_coverage: float = 0.0005
    min_text_characters: int = 10
    min_words: int = 2
    min_agreement_when_available: float = 45.0


@dataclass(frozen=True)
class CandidateRegion:
    bbox: tuple[int, int, int, int]
    text: str
    confidence: float | None


@dataclass(frozen=True)
class OCRCandidate:
    route: ExtractionRoute
    text: str
    mean_confidence: float | None
    psm: int | str | None
    language_profile: str | None
    preprocessing: str | None
    word_count: int
    coverage: float
    regions: tuple[CandidateRegion, ...] = ()
    structurally_valid: bool = True
    reading_order_valid: bool = True
    quality_score: float = 0.0
    agreement_score: float | None = None
    selection_score: float = 0.0
    meaningful_character_ratio: float = 0.0
    garbage_ratio: float = 0.0
    repetition_ratio: float = 0.0
    quality_gate_passed: bool = False
    rejection_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateSelection:
    selected: OCRCandidate | None
    candidates: tuple[OCRCandidate, ...]
    fallback_reasons: tuple[str, ...]


def normalize_ocr_text(text: str) -> str:
    """Normalize presentation variants while retaining meaningful letters."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ـ": ""}))
    text = text.replace("\u200d", "").replace("\ufeff", "").replace("\u00ad", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _text_metrics(text: str) -> tuple[float, float, float, int, int]:
    normalized = normalize_ocr_text(text)
    compact = "".join(character for character in normalized if not character.isspace())
    words = re.findall(r"\w+", normalized, flags=re.UNICODE)
    if not compact:
        return 0.0, 1.0, 1.0, 0, 0

    meaningful = sum(character.isalnum() for character in compact) / len(compact)
    garbage = sum(
        character in {"\ufffd", "\u25a1", "\u25a0", "\u25c6"}
        or unicodedata.category(character) in {"Cc", "Cs", "Co"}
        for character in compact
    ) / len(compact)
    repetition = 1.0 - (len({word.casefold() for word in words}) / len(words)) if words else 1.0
    return meaningful, garbage, repetition, len(compact), len(words)


def score_candidate(candidate: OCRCandidate) -> OCRCandidate:
    meaningful, garbage, repetition, character_count, word_count = _text_metrics(candidate.text)
    length_score = min(character_count / 120.0, 1.0)
    coverage_score = min(max(candidate.coverage, 0.0) / 0.02, 1.0)
    text_score = 100.0 * (
        meaningful * 0.40
        + (1.0 - garbage) * 0.20
        + (1.0 - repetition) * 0.15
        + length_score * 0.15
        + coverage_score * 0.10
    )
    confidence = candidate.mean_confidence
    quality = text_score if confidence is None else text_score * 0.70 + confidence * 0.30
    return replace(
        candidate,
        text=normalize_ocr_text(candidate.text),
        word_count=word_count,
        quality_score=round(max(0.0, min(100.0, quality)), 2),
        meaningful_character_ratio=round(meaningful, 4),
        garbage_ratio=round(garbage, 4),
        repetition_ratio=round(repetition, 4),
    )


def candidate_similarity(first: str, second: str) -> float:
    first = " ".join(normalize_ocr_text(first).casefold().split())
    second = " ".join(normalize_ocr_text(second).casefold().split())
    if not first or not second:
        return 0.0
    sequence = SequenceMatcher(None, first, second).ratio()
    first_words, second_words = set(first.split()), set(second.split())
    overlap = len(first_words & second_words) / max(1, min(len(first_words), len(second_words)))
    return round((sequence * 0.45 + overlap * 0.55) * 100.0, 2)


def _with_agreement(candidates: list[OCRCandidate]) -> list[OCRCandidate]:
    if len(candidates) < 2:
        return [replace(candidate, agreement_score=None) for candidate in candidates]
    result = []
    for index, candidate in enumerate(candidates):
        scores = sorted(
            (
                candidate_similarity(candidate.text, other.text)
                for other_index, other in enumerate(candidates)
                if other_index != index
            ),
            reverse=True,
        )[:3]
        result.append(replace(candidate, agreement_score=round(sum(scores) / len(scores), 2)))
    return result


def apply_quality_gate(candidate: OCRCandidate, policy: QualityGatePolicy) -> OCRCandidate:
    reasons: list[str] = []
    confidence = candidate.mean_confidence
    if not candidate.structurally_valid:
        reasons.append("structurally_invalid")
    if candidate.route == ExtractionRoute.REGION_OCR and not candidate.reading_order_valid:
        reasons.append("invalid_region_reading_order")
    if len("".join(candidate.text.split())) < policy.min_text_characters:
        reasons.append("ocr_text_too_short")
    if candidate.word_count < policy.min_words:
        reasons.append("ocr_word_count_below_threshold")
    if confidence is None or confidence < policy.min_mean_confidence:
        reasons.append("ocr_confidence_below_threshold")
    if candidate.quality_score < policy.min_quality_score:
        reasons.append("ocr_quality_below_threshold")
    if candidate.meaningful_character_ratio < policy.min_meaningful_character_ratio:
        reasons.append("meaningful_character_ratio_below_threshold")
    if candidate.garbage_ratio > policy.max_garbage_ratio:
        reasons.append("garbage_ratio_above_threshold")
    if candidate.repetition_ratio > policy.max_repetition_ratio:
        reasons.append("repetition_ratio_above_threshold")
    if candidate.coverage < policy.min_coverage:
        reasons.append("ocr_coverage_below_threshold")
    if (
        candidate.agreement_score is not None
        and candidate.agreement_score < policy.min_agreement_when_available
    ):
        reasons.append("ocr_agreement_below_threshold")

    if candidate.agreement_score is None:
        selection = candidate.quality_score * 0.5625 + (confidence or 0.0) * 0.4375
    else:
        selection = (
            candidate.quality_score * 0.45
            + (confidence or 0.0) * 0.35
            + candidate.agreement_score * 0.20
        )
    return replace(
        candidate,
        selection_score=round(max(0.0, min(100.0, selection)), 2),
        quality_gate_passed=not reasons,
        rejection_reasons=tuple(reasons),
    )


def _candidate_sort_key(candidate: OCRCandidate) -> tuple:
    text_digest = hashlib.sha256(candidate.text.encode("utf-8")).hexdigest()
    return (
        -candidate.selection_score,
        -candidate.quality_score,
        -(candidate.mean_confidence or 0.0),
        int(candidate.psm) if isinstance(candidate.psm, int) else 999,
        candidate.language_profile or "",
        candidate.preprocessing or "",
        text_digest,
    )


def select_candidate(
    candidates: list[OCRCandidate],
    *,
    policy: QualityGatePolicy,
    region_min_advantage: float,
) -> CandidateSelection:
    """Select by evidence; layout complexity is intentionally not an input."""
    if region_min_advantage < 0:
        raise ValueError("region_min_advantage must be non-negative.")

    scored = [score_candidate(candidate) for candidate in candidates]
    gated = [apply_quality_gate(candidate, policy) for candidate in _with_agreement(scored)]
    valid = [candidate for candidate in gated if candidate.quality_gate_passed]
    full = sorted(
        (candidate for candidate in valid if candidate.route == ExtractionRoute.FULL_PAGE_OCR),
        key=_candidate_sort_key,
    )
    region = sorted(
        (candidate for candidate in valid if candidate.route == ExtractionRoute.REGION_OCR),
        key=_candidate_sort_key,
    )

    reasons: list[str] = []
    if not valid:
        reasons.append("all_ocr_candidates_rejected")
        return CandidateSelection(None, tuple(sorted(gated, key=_candidate_sort_key)), tuple(reasons))
    if full and region:
        selected = region[0] if (
            region[0].selection_score >= full[0].selection_score + region_min_advantage
        ) else full[0]
        if selected.route == ExtractionRoute.REGION_OCR:
            reasons.append("region_candidate_met_required_advantage")
        else:
            reasons.append("full_page_candidate_not_outscored_by_region_margin")
    else:
        selected = (full or region)[0]
        reasons.append("only_one_ocr_route_passed_quality_gate")
    return CandidateSelection(selected, tuple(sorted(gated, key=_candidate_sort_key)), tuple(reasons))


def candidate_metrics(candidate: OCRCandidate) -> OCRCandidateMetrics:
    return OCRCandidateMetrics(
        route=candidate.route,
        psm=candidate.psm if candidate.psm == "mixed" or isinstance(candidate.psm, int) else None,
        language_profile=candidate.language_profile,
        preprocessing=candidate.preprocessing,
        mean_confidence=candidate.mean_confidence,
        quality_score=candidate.quality_score,
        agreement_score=candidate.agreement_score,
        selection_score=candidate.selection_score,
        text_length=len(candidate.text),
        word_count=candidate.word_count,
        meaningful_character_ratio=candidate.meaningful_character_ratio,
        garbage_ratio=candidate.garbage_ratio,
        repetition_ratio=candidate.repetition_ratio,
        coverage=candidate.coverage,
        structurally_valid=candidate.structurally_valid,
        reading_order_valid=candidate.reading_order_valid,
        quality_gate_passed=candidate.quality_gate_passed,
        rejection_reasons=list(candidate.rejection_reasons),
    )
