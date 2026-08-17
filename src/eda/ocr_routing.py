"""Pure routing policy for contract tests and the next OCR integration step."""

from __future__ import annotations

from dataclasses import dataclass

from eda.ingestion_schema import ExtractionRoute, PageType, ProcessingStatus


@dataclass(frozen=True)
class RoutingOutcome:
    selected_route: ExtractionRoute
    processing_status: ProcessingStatus
    quality_gate_passed: bool


def choose_extraction_route(
    *,
    page_type: PageType,
    native_text: str,
    ocr_text: str,
    ocr_quality_gate_passed: bool,
    preferred_ocr_route: ExtractionRoute = ExtractionRoute.FULL_PAGE_OCR,
) -> RoutingOutcome:
    """Choose a deterministic route without running OCR.

    Mixed content keeps both layers when OCR passes. Rejected OCR never becomes
    accepted; usable native text is retained but marked for review when OCR was
    expected and failed.
    """
    if preferred_ocr_route not in {
        ExtractionRoute.FULL_PAGE_OCR,
        ExtractionRoute.REGION_OCR,
    }:
        raise ValueError("preferred_ocr_route must be a concrete OCR route.")

    has_native = bool(native_text.strip())
    has_ocr = bool(ocr_text.strip())

    if has_native and has_ocr and ocr_quality_gate_passed:
        return RoutingOutcome(
            ExtractionRoute.COMBINED,
            ProcessingStatus.ACCEPTED,
            True,
        )
    if has_native:
        accepted = page_type == PageType.DIGITAL and not has_ocr
        return RoutingOutcome(
            ExtractionRoute.NATIVE,
            ProcessingStatus.ACCEPTED if accepted else ProcessingStatus.NEEDS_REVIEW,
            accepted,
        )
    if has_ocr and ocr_quality_gate_passed:
        return RoutingOutcome(
            preferred_ocr_route,
            ProcessingStatus.ACCEPTED,
            True,
        )
    if has_ocr:
        return RoutingOutcome(
            ExtractionRoute.REJECTED,
            ProcessingStatus.NEEDS_REVIEW,
            False,
        )
    return RoutingOutcome(
        ExtractionRoute.REJECTED,
        ProcessingStatus.FAILED,
        False,
    )
