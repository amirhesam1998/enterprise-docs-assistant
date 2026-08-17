"""Ground-truth-aware OCR and routing evaluation utilities."""

from __future__ import annotations

import re
import statistics
import unicodedata
from dataclasses import dataclass
from typing import Sequence, TypeVar


T = TypeVar("T")


def normalize_persian_for_evaluation(text: str) -> str:
    """Normalize glyph variants, optional vocalization marks, and whitespace—not letters."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ـ": ""}))
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = text.replace("\u200c", " ").replace("\u200d", "").replace("\ufeff", "")
    return " ".join(text.split())


def _edit_distance(reference: Sequence[T], hypothesis: Sequence[T]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def normalized_cer(hypothesis: str, ground_truth: str | None) -> float | None:
    """Return CER only when approved, non-empty ground truth is supplied."""
    if ground_truth is None:
        return None
    reference = normalize_persian_for_evaluation(ground_truth)
    if not reference:
        return None
    hypothesis = normalize_persian_for_evaluation(hypothesis)
    return _edit_distance(reference, hypothesis) / len(reference)


def normalized_wer(hypothesis: str, ground_truth: str | None) -> float | None:
    """Return WER only when approved, non-empty ground truth is supplied."""
    if ground_truth is None:
        return None
    reference = normalize_persian_for_evaluation(ground_truth).split()
    if not reference:
        return None
    hypothesis = normalize_persian_for_evaluation(hypothesis).split()
    return _edit_distance(reference, hypothesis) / len(reference)


def categorical_accuracy(actual: Sequence[T], expected: Sequence[T]) -> float | None:
    if len(actual) != len(expected):
        raise ValueError("actual and expected must have equal lengths.")
    return sum(left == right for left, right in zip(actual, expected)) / len(expected) if expected else None


def route_accuracy(actual: Sequence[str], expected: Sequence[str]) -> float | None:
    return categorical_accuracy(actual, expected)


def page_classification_accuracy(actual: Sequence[str], expected: Sequence[str]) -> float | None:
    return categorical_accuracy(actual, expected)


def extraction_coverage(extracted_pages: int, total_pages: int) -> float | None:
    if extracted_pages < 0 or total_pages < 0 or extracted_pages > total_pages:
        raise ValueError("Page counts must satisfy 0 <= extracted_pages <= total_pages.")
    return extracted_pages / total_pages if total_pages else None


def failure_rate(failed_pages: int, total_pages: int) -> float | None:
    if failed_pages < 0 or total_pages < 0 or failed_pages > total_pages:
        raise ValueError("Page counts must satisfy 0 <= failed_pages <= total_pages.")
    return failed_pages / total_pages if total_pages else None


@dataclass(frozen=True)
class DurationReport:
    count: int
    total_ms: float
    mean_ms: float | None
    median_ms: float | None
    maximum_ms: float | None


def processing_duration_report(durations_ms: Sequence[float]) -> DurationReport:
    if any(duration < 0 for duration in durations_ms):
        raise ValueError("Processing durations must be non-negative.")
    if not durations_ms:
        return DurationReport(0, 0.0, None, None, None)
    return DurationReport(
        count=len(durations_ms),
        total_ms=sum(durations_ms),
        mean_ms=statistics.fmean(durations_ms),
        median_ms=statistics.median(durations_ms),
        maximum_ms=max(durations_ms),
    )
