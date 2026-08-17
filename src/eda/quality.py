"""Document / page / block extraction quality scoring.

The scorer produces a normalized 0-100 score and a four-level verdict. Its
central guarantee: a page the upstream pipeline already marked ``needs_review``
or ``failed`` can never be *upgraded* to accepted by a high text score, and
garbage text can never reach the accepted band. Scores are relative operating
signals, not validated OCR benchmarks — real Persian/English documents are still
required to calibrate the thresholds.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from eda.ingestion_schema import (
    BlockResult,
    ExtractionRoute,
    PageResult,
    PageType,
    ProcessingStatus,
)
from eda.ocr_quality import normalize_ocr_text


class QualityLevel(str, Enum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_WARNING = "accepted_with_warning"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


# Higher rank == better. Used to take the *minimum* (worst) of a text-derived
# verdict and the ceiling implied by the pipeline's own processing status.
_LEVEL_RANK = {
    QualityLevel.FAILED: 0,
    QualityLevel.NEEDS_REVIEW: 1,
    QualityLevel.ACCEPTED_WITH_WARNING: 2,
    QualityLevel.ACCEPTED: 3,
}

_GARBAGE_CHARACTERS = {"�", "□", "■", "◆", "●", "▪", "▫"}


@dataclass(frozen=True)
class QualityThresholds:
    """Score bands. Documented defaults; overridable as constants elsewhere."""

    accepted: float = 90.0
    accepted_with_warning: float = 70.0
    needs_review: float = 40.0


DEFAULT_THRESHOLDS = QualityThresholds()


def level_for_score(score: float, thresholds: QualityThresholds = DEFAULT_THRESHOLDS) -> QualityLevel:
    if score >= thresholds.accepted:
        return QualityLevel.ACCEPTED
    if score >= thresholds.accepted_with_warning:
        return QualityLevel.ACCEPTED_WITH_WARNING
    if score >= thresholds.needs_review:
        return QualityLevel.NEEDS_REVIEW
    return QualityLevel.FAILED


def _worst(first: QualityLevel, second: QualityLevel) -> QualityLevel:
    return first if _LEVEL_RANK[first] <= _LEVEL_RANK[second] else second


def _status_ceiling(status: ProcessingStatus) -> QualityLevel:
    if status == ProcessingStatus.ACCEPTED:
        return QualityLevel.ACCEPTED
    if status == ProcessingStatus.NEEDS_REVIEW:
        return QualityLevel.NEEDS_REVIEW
    return QualityLevel.FAILED


def to_processing_status(level: QualityLevel) -> ProcessingStatus:
    if level in {QualityLevel.ACCEPTED, QualityLevel.ACCEPTED_WITH_WARNING}:
        return ProcessingStatus.ACCEPTED
    if level == QualityLevel.NEEDS_REVIEW:
        return ProcessingStatus.NEEDS_REVIEW
    return ProcessingStatus.FAILED


@dataclass(frozen=True)
class TextQualityMetrics:
    meaningful_ratio: float
    garbage_ratio: float
    repetition_ratio: float
    character_count: int
    word_count: int


def text_quality_metrics(text: str) -> TextQualityMetrics:
    """Compute language-agnostic legibility signals on normalized text."""
    normalized = normalize_ocr_text(text)
    compact = "".join(character for character in normalized if not character.isspace())
    words = re.findall(r"\w+", normalized, flags=re.UNICODE)
    if not compact:
        return TextQualityMetrics(0.0, 1.0, 1.0, 0, 0)
    meaningful = sum(character.isalnum() for character in compact) / len(compact)
    garbage = sum(
        character in _GARBAGE_CHARACTERS
        or unicodedata.category(character) in {"Cc", "Cs", "Co"}
        for character in compact
    ) / len(compact)
    repetition = 1.0 - (len({word.casefold() for word in words}) / len(words)) if words else 1.0
    return TextQualityMetrics(
        meaningful_ratio=round(meaningful, 4),
        garbage_ratio=round(garbage, 4),
        repetition_ratio=round(repetition, 4),
        character_count=len(compact),
        word_count=len(words),
    )


def score_text(text: str) -> float:
    """Return a 0-100 legibility score from text signals alone."""
    metrics = text_quality_metrics(text)
    if metrics.character_count == 0:
        return 0.0
    length_score = min(metrics.character_count / 200.0, 1.0)
    score = 100.0 * (
        metrics.meaningful_ratio * 0.45
        + (1.0 - metrics.garbage_ratio) * 0.25
        + (1.0 - metrics.repetition_ratio) * 0.15
        + length_score * 0.15
    )
    return round(max(0.0, min(100.0, score)), 2)


@dataclass(frozen=True)
class BlockQuality:
    block_id: str
    block_type: str
    score: float
    level: QualityLevel
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "block_type": self.block_type,
            "score": self.score,
            "level": self.level.value,
            "warnings": list(self.warnings),
        }


def score_block(block: BlockResult) -> BlockQuality:
    score = block.quality_score if block.quality_score is not None else score_text(block.text)
    warnings: list[str] = []
    metrics = text_quality_metrics(block.text)
    if metrics.garbage_ratio > 0.1:
        warnings.append("high_garbage_ratio")
    if metrics.repetition_ratio > 0.8:
        warnings.append("high_repetition_ratio")
    return BlockQuality(
        block_id=str(block.block_id),
        block_type=block.block_type.value,
        score=round(score, 2),
        level=level_for_score(score),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class PageQuality:
    page_number: int
    score: float
    level: QualityLevel
    status: ProcessingStatus
    is_empty: bool
    warnings: tuple[str, ...] = ()
    block_qualities: tuple[BlockQuality, ...] = ()

    def as_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "score": self.score,
            "level": self.level.value,
            "status": self.status.value,
            "is_empty": self.is_empty,
            "warnings": list(self.warnings),
            "blocks": [block.as_dict() for block in self.block_qualities],
        }


def score_page(page: PageResult) -> PageQuality:
    """Score a page, never ranking it above its own pipeline status ceiling."""
    warnings: list[str] = []
    index_text = page.index_text.strip()
    is_empty = not index_text or page.page_type == PageType.EMPTY

    if is_empty:
        score = 0.0
    else:
        text_score = score_text(index_text)
        decision = page.ocr_decision
        if decision.quality_score is not None:
            score = 0.6 * text_score + 0.4 * decision.quality_score
        else:
            score = text_score
        # When both layers exist, cross-layer agreement is corroborating evidence.
        if page.native_text.strip() and page.ocr_text.strip() and decision.agreement_score is not None:
            score = 0.85 * score + 0.15 * decision.agreement_score
        score = round(max(0.0, min(100.0, score)), 2)

    if page.ocr_decision.selected_route == ExtractionRoute.REJECTED and not is_empty:
        warnings.append("extraction_route_rejected")
        score = min(score, DEFAULT_THRESHOLDS.needs_review - 0.01)
    if page.ocr_decision.fallback_reasons:
        warnings.append("fallback_route_used")
    if not page.ocr_decision.quality_gate_passed:
        warnings.append("quality_gate_not_passed")

    text_level = level_for_score(score)
    level = _worst(text_level, _status_ceiling(page.processing_status))
    return PageQuality(
        page_number=page.page_number,
        score=score,
        level=level,
        status=to_processing_status(level),
        is_empty=is_empty,
        warnings=tuple(dict.fromkeys(warnings)),
        block_qualities=tuple(score_block(block) for block in page.blocks),
    )


@dataclass(frozen=True)
class QualityReport:
    document_id: str
    score: float
    level: QualityLevel
    total_pages: int
    accepted_pages: int
    needs_review_pages: int
    failed_pages: int
    empty_pages: int
    page_qualities: tuple[PageQuality, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "score": self.score,
            "level": self.level.value,
            "total_pages": self.total_pages,
            "accepted_pages": self.accepted_pages,
            "needs_review_pages": self.needs_review_pages,
            "failed_pages": self.failed_pages,
            "empty_pages": self.empty_pages,
            "warnings": list(self.warnings),
            "pages": [page.as_dict() for page in self.page_qualities],
        }


def score_document(document_id: str, pages: list[PageResult] | tuple[PageResult, ...]) -> QualityReport:
    """Aggregate page scores; a document with no accepted page is never accepted."""
    page_qualities = tuple(score_page(page) for page in pages)
    if not page_qualities:
        return QualityReport(document_id, 0.0, QualityLevel.FAILED, 0, 0, 0, 0, 0)

    accepted = sum(pq.status == ProcessingStatus.ACCEPTED for pq in page_qualities)
    needs_review = sum(pq.status == ProcessingStatus.NEEDS_REVIEW for pq in page_qualities)
    failed = sum(pq.status == ProcessingStatus.FAILED for pq in page_qualities)
    empty = sum(pq.is_empty for pq in page_qualities)

    mean_score = round(sum(pq.score for pq in page_qualities) / len(page_qualities), 2)
    level = level_for_score(mean_score)
    if accepted == 0:
        level = _worst(level, QualityLevel.NEEDS_REVIEW)

    warnings: list[str] = []
    if failed:
        warnings.append(f"{failed}_failed_pages")
    if needs_review:
        warnings.append(f"{needs_review}_pages_need_review")
    return QualityReport(
        document_id=document_id,
        score=mean_score,
        level=level,
        total_pages=len(page_qualities),
        accepted_pages=accepted,
        needs_review_pages=needs_review,
        failed_pages=failed,
        empty_pages=empty,
        page_qualities=page_qualities,
        warnings=tuple(warnings),
    )
