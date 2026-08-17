"""Reusable, typed adaptive PDF extraction.

The native parser remains the default entry point. This module performs no
indexing and keeps rendered pages in memory, one page at a time.
"""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Callable, Iterable

import cv2
import pymupdf
import pytesseract
from PIL import Image
from pytesseract import Output

from eda.identifiers import (
    document_id as build_document_id,
    page_id as build_page_id,
    region_id as build_region_id,
    revision_id as build_revision_id,
    sha256_file,
)
from eda.ingestion_schema import (
    DocumentManifest,
    ExtractionRoute,
    OCRDecision,
    PageResult,
    PageType,
    ProcessingProvenance,
    ProcessingStatus,
    TextLayer,
    TextRegion,
    safe_git_revision,
)
from eda.ocr import preprocess_for_ocr, reconstruct_text
from eda.ocr_quality import (
    CandidateRegion,
    CandidateSelection,
    OCRCandidate,
    QualityGatePolicy,
    candidate_metrics,
    normalize_ocr_text,
    score_candidate,
    select_candidate,
)
from eda.ocr_regions import detect_text_regions
from eda.pdf_analysis import (
    PageClassification,
    PageClassificationPolicy,
    PageEvidence,
    classify_page,
    collect_page_evidence,
)


SUPPORTED_LANGUAGE_PROFILES = ("fas+eng", "fas", "eng")
SUPPORTED_PSM_VALUES = frozenset(range(3, 14))
SUPPORTED_PREPROCESSING = ("original", "enhanced", "binary")
PIPELINE_NAME = "adaptive_pdf_ocr"
PIPELINE_VERSION = "1.0"


class AdaptivePDFError(RuntimeError):
    """Base exception safe to expose without a private source path."""


class UnreadablePDFError(AdaptivePDFError):
    pass


class EncryptedPDFError(AdaptivePDFError):
    pass


class InvalidPageRangeError(AdaptivePDFError):
    pass


class RenderingError(AdaptivePDFError):
    pass


class OCRUnavailableError(AdaptivePDFError):
    pass


class OCRLanguageUnavailableError(AdaptivePDFError):
    pass


class OCRTimeoutError(AdaptivePDFError):
    pass


@dataclass(frozen=True)
class AdaptiveOCRConfig:
    render_dpi: int = 220
    language_profiles: tuple[str, ...] = ("fas+eng", "fas", "eng")
    psm_candidates: tuple[int, ...] = (3, 6, 11)
    preprocessing_candidates: tuple[str, ...] = ("original", "enhanced")
    max_candidate_count: int = 8
    region_min_advantage: float = 5.0
    complex_layout_min_regions: int = 3
    ocr_timeout_seconds: int = 60
    reading_direction: str = "rtl"
    quality_gate: QualityGatePolicy = field(default_factory=QualityGatePolicy)
    classification: PageClassificationPolicy = field(default_factory=PageClassificationPolicy)

    def __post_init__(self) -> None:
        if self.render_dpi < 72:
            raise ValueError("render_dpi must be at least 72.")
        if not self.language_profiles or any(
            profile not in SUPPORTED_LANGUAGE_PROFILES for profile in self.language_profiles
        ):
            raise ValueError("language_profiles must use fas+eng, fas, or eng.")
        if not self.psm_candidates or any(psm not in SUPPORTED_PSM_VALUES for psm in self.psm_candidates):
            raise ValueError("psm_candidates contains an unsupported Tesseract PSM.")
        if not self.preprocessing_candidates or any(
            mode not in SUPPORTED_PREPROCESSING for mode in self.preprocessing_candidates
        ):
            raise ValueError("Unsupported OCR preprocessing candidate.")
        if self.max_candidate_count < 1:
            raise ValueError("max_candidate_count must be positive.")
        if self.region_min_advantage < 0:
            raise ValueError("region_min_advantage must be non-negative.")
        if self.complex_layout_min_regions < 1:
            raise ValueError("complex_layout_min_regions must be positive.")
        if self.ocr_timeout_seconds < 1:
            raise ValueError("ocr_timeout_seconds must be positive.")
        if self.reading_direction not in {"rtl", "ltr"}:
            raise ValueError("reading_direction must be rtl or ltr.")


@dataclass(frozen=True)
class CandidatePlan:
    route: ExtractionRoute
    psm: int
    language_profile: str
    preprocessing: str


@dataclass(frozen=True)
class CandidateBatch:
    candidates: tuple[OCRCandidate, ...]
    detected_boxes: tuple[tuple[int, int, int, int], ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdaptiveExtraction:
    manifest: DocumentManifest
    pages: tuple[PageResult, ...]


CandidateProvider = Callable[[Image.Image, PageEvidence, AdaptiveOCRConfig], CandidateBatch]


def render_page(page: pymupdf.Page, dpi: int) -> Image.Image:
    try:
        pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    except Exception as error:
        raise RenderingError("PDF page rendering failed.") from error


def _intersection_over_minimum(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / max(1, min(first_area, second_area))


def sanitize_region_boxes(
    boxes: Iterable[tuple[int, int, int, int]],
    *,
    page_width: int,
    page_height: int,
) -> list[tuple[int, int, int, int]]:
    """Clamp boxes and merge only obvious duplicate/contained detections."""
    valid: list[tuple[int, int, int, int]] = []
    for raw in boxes:
        if len(raw) != 4:
            continue
        left, top, right, bottom = map(int, raw)
        clamped = (
            max(0, min(left, page_width)),
            max(0, min(top, page_height)),
            max(0, min(right, page_width)),
            max(0, min(bottom, page_height)),
        )
        if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
            continue
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(valid)
                if _intersection_over_minimum(existing, clamped) >= 0.85
            ),
            None,
        )
        if duplicate_index is None:
            valid.append(clamped)
        else:
            existing = valid[duplicate_index]
            valid[duplicate_index] = (
                min(existing[0], clamped[0]),
                min(existing[1], clamped[1]),
                max(existing[2], clamped[2]),
                max(existing[3], clamped[3]),
            )
    return sorted(set(valid), key=lambda box: (box[1], box[0], box[2], box[3]))


def order_region_boxes(
    boxes: Iterable[tuple[int, int, int, int]],
    *,
    page_width: int,
    direction: str,
) -> list[tuple[int, int, int, int]]:
    """Order distinct columns top-to-bottom, right-to-left for RTL pages."""
    boxes = list(boxes)
    if not boxes:
        return []
    spanning = [box for box in boxes if (box[2] - box[0]) >= page_width * 0.70]
    column_boxes = [box for box in boxes if box not in spanning]
    if not column_boxes:
        return sorted(spanning, key=lambda box: (box[1], -box[2] if direction == "rtl" else box[0]))

    columns: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(column_boxes, key=lambda item: (item[0], item[1])):
        target = None
        for column in columns:
            column_left = min(item[0] for item in column)
            column_right = max(item[2] for item in column)
            overlap = max(0, min(column_right, box[2]) - max(column_left, box[0]))
            if overlap / max(1, min(column_right - column_left, box[2] - box[0])) >= 0.25:
                target = column
                break
        if target is None:
            target = []
            columns.append(target)
        target.append(box)

    columns.sort(
        key=lambda column: max(box[2] for box in column),
        reverse=direction == "rtl",
    )
    ordered_columns = [
        box
        for column in columns
        for box in sorted(column, key=lambda item: (item[1], -item[2] if direction == "rtl" else item[0]))
    ]
    minimum_top = min(box[1] for box in column_boxes)
    maximum_bottom = max(box[3] for box in column_boxes)
    headers = sorted((box for box in spanning if box[3] <= minimum_top), key=lambda box: box[1])
    footers = sorted((box for box in spanning if box[1] >= maximum_bottom), key=lambda box: box[1])
    middle = sorted((box for box in spanning if box not in headers and box not in footers), key=lambda box: box[1])
    return headers + ordered_columns + middle + footers


def _candidate_plans(config: AdaptiveOCRConfig, route: ExtractionRoute) -> list[CandidatePlan]:
    return [
        CandidatePlan(route, psm, language, preprocessing)
        for language in config.language_profiles
        for psm in config.psm_candidates
        for preprocessing in config.preprocessing_candidates
    ]


def _ocr_data(
    image: Image.Image,
    plan: CandidatePlan,
    timeout: int,
) -> tuple[str, float | None, int, float]:
    prepared = preprocess_for_ocr(image, plan.preprocessing)
    try:
        data = pytesseract.image_to_data(
            prepared,
            lang=plan.language_profile,
            config=f"--oem 1 --psm {plan.psm}",
            output_type=Output.DICT,
            timeout=timeout,
        )
    except RuntimeError as error:
        raise OCRTimeoutError("OCR candidate timed out.") from error
    except pytesseract.TesseractNotFoundError as error:
        raise OCRUnavailableError("Tesseract is unavailable in adaptive mode.") from error
    except pytesseract.TesseractError as error:
        raise AdaptivePDFError("Tesseract rejected an OCR candidate.") from error

    confidences: list[float] = []
    covered_area = 0
    for index, raw_word in enumerate(data.get("text", [])):
        if not str(raw_word).strip():
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if confidence < 0:
            continue
        confidences.append(confidence)
        try:
            covered_area += max(0, int(data["width"][index])) * max(0, int(data["height"][index]))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    page_area = max(1, image.width * image.height)
    return (
        normalize_ocr_text(reconstruct_text(data)),
        round(fmean(confidences), 2) if confidences else None,
        len(confidences),
        round(min(covered_area / page_area, 1.0), 6),
    )


def _run_full_page_candidate(image: Image.Image, plan: CandidatePlan, timeout: int) -> OCRCandidate:
    text, confidence, words, coverage = _ocr_data(image, plan, timeout)
    regions = (
        CandidateRegion((0, 0, image.width, image.height), text, confidence),
    ) if text else ()
    return OCRCandidate(
        route=ExtractionRoute.FULL_PAGE_OCR,
        text=text,
        mean_confidence=confidence,
        psm=plan.psm,
        language_profile=plan.language_profile,
        preprocessing=plan.preprocessing,
        word_count=words,
        coverage=coverage,
        regions=regions,
        structurally_valid=bool(text),
    )


def _run_region_candidate(
    image: Image.Image,
    boxes: list[tuple[int, int, int, int]],
    plan: CandidatePlan,
    timeout: int,
) -> OCRCandidate:
    regions: list[CandidateRegion] = []
    confidences: list[float] = []
    total_words = 0
    page_coverage = 0.0
    seen_text: set[str] = set()
    for box in boxes:
        crop = image.crop(box)
        text, confidence, words, local_coverage = _ocr_data(crop, plan, timeout)
        normalized_key = " ".join(text.casefold().split())
        if not normalized_key or normalized_key in seen_text:
            continue
        seen_text.add(normalized_key)
        regions.append(CandidateRegion(box, text, confidence))
        total_words += words
        if confidence is not None:
            confidences.extend([confidence] * max(words, 1))
        box_area = (box[2] - box[0]) * (box[3] - box[1])
        page_coverage += local_coverage * box_area / max(1, image.width * image.height)
    text = normalize_ocr_text("\n\n".join(region.text for region in regions))
    return OCRCandidate(
        route=ExtractionRoute.REGION_OCR,
        text=text,
        mean_confidence=round(fmean(confidences), 2) if confidences else None,
        psm=plan.psm,
        language_profile=plan.language_profile,
        preprocessing=plan.preprocessing,
        word_count=total_words,
        coverage=round(min(page_coverage, 1.0), 6),
        regions=tuple(regions),
        structurally_valid=bool(regions),
        reading_order_valid=all(first.bbox != second.bbox for first, second in zip(regions, regions[1:])),
    )


def generate_ocr_candidates(
    image: Image.Image,
    evidence: PageEvidence,
    config: AdaptiveOCRConfig,
) -> CandidateBatch:
    """Generate a bounded candidate set; region work is conditional."""
    candidates: list[OCRCandidate] = []
    warnings: list[str] = []
    errors: list[str] = []
    full_plans = _candidate_plans(config, ExtractionRoute.FULL_PAGE_OCR)
    reserve_for_region = 1 if config.max_candidate_count > 1 else 0
    for plan in full_plans[: config.max_candidate_count - reserve_for_region]:
        try:
            candidates.append(_run_full_page_candidate(image, plan, config.ocr_timeout_seconds))
        except OCRTimeoutError:
            warnings.append("ocr_candidate_timeout")
        except AdaptivePDFError:
            errors.append("full_page_ocr_candidate_failed")

    probe_language = config.language_profiles[0]
    try:
        raw_regions = detect_text_regions(
            image,
            languages=probe_language,
            psm=11,
            direction=config.reading_direction,
            padding=12,
            timeout=config.ocr_timeout_seconds,
        )
        boxes = sanitize_region_boxes(
            (region.box for region in raw_regions),
            page_width=image.width,
            page_height=image.height,
        )
        boxes = order_region_boxes(boxes, page_width=image.width, direction=config.reading_direction)
    except RuntimeError:
        warnings.append("region_detection_timeout")
        boxes = []
    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError):
        errors.append("region_detection_failed")
        boxes = []

    full_selection = select_candidate(
        candidates,
        policy=config.quality_gate,
        region_min_advantage=config.region_min_advantage,
    )
    complex_layout = len(boxes) >= config.complex_layout_min_regions
    should_run_regions = bool(boxes) and (complex_layout or full_selection.selected is None)
    if complex_layout:
        warnings.append("complex_layout_triggered_region_candidate_generation")

    remaining = config.max_candidate_count - len(candidates)
    if should_run_regions and remaining:
        for plan in _candidate_plans(config, ExtractionRoute.REGION_OCR)[:remaining]:
            try:
                candidates.append(_run_region_candidate(image, boxes, plan, config.ocr_timeout_seconds))
            except OCRTimeoutError:
                warnings.append("region_ocr_candidate_timeout")
            except AdaptivePDFError:
                errors.append("region_ocr_candidate_failed")
    return CandidateBatch(tuple(candidates), tuple(boxes), tuple(dict.fromkeys(warnings)), tuple(dict.fromkeys(errors)))


def _validate_tesseract(config: AdaptiveOCRConfig) -> tuple[str, ...]:
    command = os.getenv("TESSERACT_CMD")
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    try:
        available = set(pytesseract.get_languages(config=""))
    except pytesseract.TesseractNotFoundError as error:
        raise OCRUnavailableError("Tesseract is unavailable in adaptive mode.") from error
    missing = sorted(
        language
        for profile in config.language_profiles
        for language in profile.split("+")
        if language not in available
    )
    if missing:
        raise OCRLanguageUnavailableError(
            "Requested Tesseract language packs are unavailable: " + ", ".join(sorted(set(missing)))
        )
    return config.language_profiles


def _provenance(
    *,
    digest: str,
    config: AdaptiveOCRConfig,
    timestamp: datetime,
    resolved_languages: tuple[str, ...],
) -> ProcessingProvenance:
    try:
        tesseract_version = str(pytesseract.get_tesseract_version())
    except (OSError, pytesseract.TesseractNotFoundError):
        tesseract_version = None
    return ProcessingProvenance(
        pipeline_name=PIPELINE_NAME,
        pipeline_version=PIPELINE_VERSION,
        input_sha256=digest,
        dpi=config.render_dpi,
        requested_language_profiles=list(config.language_profiles),
        resolved_language_profiles=list(resolved_languages),
        python_version=platform.python_version(),
        tesseract_version=tesseract_version,
        pymupdf_version=str(getattr(pymupdf, "VersionBind", "unknown")),
        opencv_version=cv2.__version__,
        platform=f"{platform.system()} {platform.release()} {platform.machine()}".strip(),
        code_revision=safe_git_revision(),
        processing_timestamp=timestamp,
    )


def _native_regions(
    evidence: PageEvidence,
    *,
    document_page_id: str,
) -> list[TextRegion]:
    scale_x = evidence.rendered_width_pixels / max(evidence.page_width_points, 1.0)
    scale_y = evidence.rendered_height_pixels / max(evidence.page_height_points, 1.0)
    blocks = sorted(evidence.native_blocks, key=lambda block: (block.bbox_points[1], -block.bbox_points[2]))
    regions = []
    for order, block in enumerate(blocks):
        left, top, right, bottom = block.bbox_points
        bbox = (
            max(0.0, left * scale_x),
            max(0.0, top * scale_y),
            min(float(evidence.rendered_width_pixels), right * scale_x),
            min(float(evidence.rendered_height_pixels), bottom * scale_y),
        )
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        regions.append(
            TextRegion(
                region_id=build_region_id(document_page_id, TextLayer.NATIVE.value, ExtractionRoute.NATIVE.value, order),
                source_layer=TextLayer.NATIVE,
                text=block.text,
                bbox=bbox,
                reading_order=len(regions),
                confidence=None,
                language_profile=None,
            )
        )
    return regions


def _selected_ocr_regions(
    candidate: OCRCandidate | None,
    *,
    document_page_id: str,
    starting_order: int,
) -> list[TextRegion]:
    if candidate is None:
        return []
    return [
        TextRegion(
            region_id=build_region_id(
                document_page_id,
                TextLayer.OCR.value,
                candidate.route.value,
                order,
            ),
            source_layer=TextLayer.OCR,
            text=region.text,
            bbox=region.bbox,
            reading_order=starting_order + order,
            confidence=region.confidence,
            language_profile=candidate.language_profile,
            metadata={"table_structure": "not_extracted"},
        )
        for order, region in enumerate(candidate.regions)
        if region.text.strip()
    ]


def build_page_result(
    *,
    evidence: PageEvidence,
    preliminary_classification: PageClassification,
    candidate_batch: CandidateBatch,
    config: AdaptiveOCRConfig,
    document_id: str,
    revision_id: str,
    page_index: int,
    provenance: ProcessingProvenance,
    processing_time_ms: float,
) -> PageResult:
    selection: CandidateSelection = select_candidate(
        list(candidate_batch.candidates),
        policy=config.quality_gate,
        region_min_advantage=config.region_min_advantage,
    )
    selected = selection.selected
    best_rejected = selection.candidates[0] if selection.candidates else None
    diagnostic_candidate = selected or best_rejected
    ocr_text = diagnostic_candidate.text if diagnostic_candidate else ""
    classification = classify_page(
        evidence,
        policy=config.classification,
        accepted_ocr_text=selected.text if selected else "",
    )
    native_text = evidence.native_text
    has_native = bool(native_text.strip())

    if selected and has_native and classification.page_type == PageType.MIXED:
        selected_route = ExtractionRoute.COMBINED
        status = ProcessingStatus.NEEDS_REVIEW
    elif selected:
        selected_route = selected.route
        status = ProcessingStatus.ACCEPTED
    elif has_native:
        selected_route = ExtractionRoute.NATIVE
        status = (
            ProcessingStatus.ACCEPTED
            if preliminary_classification.page_type == PageType.DIGITAL
            and preliminary_classification.native_text_usable
            else ProcessingStatus.NEEDS_REVIEW
        )
    else:
        selected_route = ExtractionRoute.REJECTED
        status = ProcessingStatus.NEEDS_REVIEW if ocr_text else ProcessingStatus.FAILED

    if selected_route == ExtractionRoute.NATIVE:
        native_candidate = score_candidate(
            OCRCandidate(
                route=ExtractionRoute.NATIVE,
                text=native_text,
                mean_confidence=None,
                psm=None,
                language_profile=None,
                preprocessing=None,
                word_count=0,
                coverage=evidence.visual_content_ratio,
            )
        )
        mean_confidence = agreement = selection_score = None
        quality_score = native_candidate.quality_score
        gate_passed = status == ProcessingStatus.ACCEPTED
        selected_psm = selected_language = selected_preprocessing = None
    elif selected:
        mean_confidence = selected.mean_confidence
        quality_score = selected.quality_score
        agreement = selected.agreement_score
        selection_score = selected.selection_score
        gate_passed = selected.quality_gate_passed
        selected_psm = selected.psm if selected.psm == "mixed" or isinstance(selected.psm, int) else None
        selected_language = selected.language_profile
        selected_preprocessing = selected.preprocessing
    else:
        mean_confidence = best_rejected.mean_confidence if best_rejected else None
        quality_score = best_rejected.quality_score if best_rejected else None
        agreement = best_rejected.agreement_score if best_rejected else None
        selection_score = best_rejected.selection_score if best_rejected else None
        gate_passed = False
        selected_psm = selected_language = selected_preprocessing = None

    fallback_reasons = list(selection.fallback_reasons)
    if selected is None and has_native:
        fallback_reasons.append("usable_native_text_preserved_after_ocr_rejection")
    if selected_route == ExtractionRoute.COMBINED:
        fallback_reasons.append("mixed_layers_preserved_without_coordinate_merge")
    if classification.page_type == PageType.EMPTY:
        fallback_reasons.append("empty_page_detected")

    document_page_id = build_page_id(revision_id, page_index)
    native_regions = _native_regions(evidence, document_page_id=document_page_id)
    ocr_regions = _selected_ocr_regions(
        diagnostic_candidate,
        document_page_id=document_page_id,
        starting_order=len(native_regions),
    )
    classification_warnings = [f"classification:{reason}" for reason in classification.reasons]
    if classification.page_type == PageType.MIXED:
        classification_warnings.append("mixed_page_requires_review_without_coordinate_merge")

    return PageResult(
        document_id=document_id,
        revision_id=revision_id,
        page_id=document_page_id,
        page_index=page_index,
        page_number=page_index + 1,
        page_type=classification.page_type,
        processing_status=status,
        native_text=native_text,
        ocr_text=ocr_text,
        regions=native_regions + ocr_regions,
        ocr_decision=OCRDecision(
            mean_confidence=mean_confidence,
            quality_score=quality_score,
            agreement_score=agreement,
            selection_score=selection_score,
            selected_route=selected_route,
            selected_psm=selected_psm,
            selected_language_profile=selected_language,
            selected_preprocessing=selected_preprocessing,
            quality_gate_passed=gate_passed,
            fallback_reasons=list(dict.fromkeys(fallback_reasons)),
            candidate_count=len(selection.candidates),
            processing_time_ms=processing_time_ms,
            candidate_metrics=[candidate_metrics(candidate) for candidate in selection.candidates],
            errors=list(candidate_batch.errors),
            warnings=list(candidate_batch.warnings),
        ),
        provenance=provenance,
        errors=list(candidate_batch.errors),
        warnings=list(dict.fromkeys(classification_warnings + list(candidate_batch.warnings))),
    )


class AdaptivePDFExtractor:
    def __init__(
        self,
        config: AdaptiveOCRConfig | None = None,
        *,
        candidate_provider: CandidateProvider | None = None,
    ) -> None:
        self.config = config or AdaptiveOCRConfig()
        self._candidate_provider = candidate_provider or generate_ocr_candidates
        self._uses_tesseract = candidate_provider is None

    def extract(
        self,
        path: str | Path,
        *,
        tenant_id: str,
        logical_document_key: str,
        source_name: str,
        page_start: int = 0,
        page_end: int | None = None,
        page_indexes: Iterable[int] | None = None,
    ) -> AdaptiveExtraction:
        source_path = Path(path)
        if not source_path.is_file():
            raise UnreadablePDFError("PDF source is unavailable or unreadable.")
        if not logical_document_key.strip():
            raise ValueError("logical_document_key is required for adaptive PDF extraction.")
        resolved_languages = _validate_tesseract(self.config) if self._uses_tesseract else self.config.language_profiles
        try:
            document = pymupdf.open(source_path)
        except Exception as error:
            raise UnreadablePDFError("PDF source could not be opened.") from error
        try:
            if document.needs_pass:
                raise EncryptedPDFError("Encrypted PDFs are not supported by adaptive extraction.")
            total_pages = document.page_count
            if page_indexes is not None:
                if page_start != 0 or page_end is not None:
                    raise InvalidPageRangeError("Use either page_indexes or a page range, not both.")
                selected_indexes = tuple(sorted(set(page_indexes)))
                if not selected_indexes or selected_indexes[0] < 0 or selected_indexes[-1] >= total_pages:
                    raise InvalidPageRangeError("PDF page_indexes contain an invalid zero-based page index.")
            else:
                end = total_pages if page_end is None else page_end
                if page_start < 0 or end <= page_start or end > total_pages:
                    raise InvalidPageRangeError("PDF page range is invalid; page_end is exclusive.")
                selected_indexes = tuple(range(page_start, end))

            digest = sha256_file(source_path)
            logical_id = build_document_id(tenant_id, logical_document_key)
            revision = build_revision_id(logical_id, digest)
            timestamp = datetime.now(timezone.utc)
            manifest = DocumentManifest(
                document_id=logical_id,
                revision_id=revision,
                tenant_id=tenant_id,
                source_name=Path(source_name).name,
                source_type="pdf",
                source_sha256=digest,
                file_size_bytes=source_path.stat().st_size,
                mime_type="application/pdf",
                total_pages=total_pages,
                parser_name=PIPELINE_NAME,
                parser_version=PIPELINE_VERSION,
                created_at=timestamp,
                metadata={"extraction_mode": "adaptive"},
            )
            pages: list[PageResult] = []
            for page_index in selected_indexes:
                started = time.perf_counter()
                page = document.load_page(page_index)
                image = render_page(page, self.config.render_dpi)
                evidence = collect_page_evidence(page, image, policy=self.config.classification)
                preliminary = classify_page(evidence, policy=self.config.classification)
                batch = (
                    CandidateBatch(())
                    if preliminary.page_type in {PageType.DIGITAL, PageType.EMPTY}
                    else self._candidate_provider(image, evidence, self.config)
                )
                provenance = _provenance(
                    digest=digest,
                    config=self.config,
                    timestamp=timestamp,
                    resolved_languages=tuple(resolved_languages),
                )
                pages.append(
                    build_page_result(
                        evidence=evidence,
                        preliminary_classification=preliminary,
                        candidate_batch=batch,
                        config=self.config,
                        document_id=logical_id,
                        revision_id=revision,
                        page_index=page_index,
                        provenance=provenance,
                        processing_time_ms=round((time.perf_counter() - started) * 1000.0, 2),
                    )
                )
            return AdaptiveExtraction(manifest, tuple(pages))
        finally:
            document.close()
