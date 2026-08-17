"""Page evidence collection and conservative PDF page classification."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf
from PIL import Image

from eda.ingestion_schema import PageType
from eda.ocr_quality import normalize_ocr_text


@dataclass(frozen=True)
class PageClassificationPolicy:
    min_native_characters: int = 40
    min_any_native_characters: int = 5
    min_meaningful_character_ratio: float = 0.55
    mixed_image_coverage: float = 0.25
    scanned_image_coverage: float = 0.50
    min_visual_content_ratio: float = 0.01
    min_dense_visual_content_ratio: float = 0.05
    max_empty_visual_content_ratio: float = 0.003
    white_pixel_threshold: int = 245


@dataclass(frozen=True)
class NativeTextBlock:
    bbox_points: tuple[float, float, float, float]
    text: str


@dataclass(frozen=True)
class PageEvidence:
    native_text: str
    normalized_native_characters: int
    meaningful_character_ratio: float
    image_coverage: float
    visual_content_ratio: float
    native_blocks: tuple[NativeTextBlock, ...]
    page_width_points: float
    page_height_points: float
    rendered_width_pixels: int
    rendered_height_pixels: int

@dataclass(frozen=True)
class PageClassification:
    page_type: PageType
    reasons: tuple[str, ...]
    native_text_usable: bool


def _meaningful_ratio(text: str) -> float:
    compact = "".join(character for character in text if not character.isspace())
    return sum(character.isalnum() for character in compact) / len(compact) if compact else 0.0


def calculate_image_coverage(page: pymupdf.Page) -> float:
    """Return capped displayed-image area; decorative images alone do not classify a scan."""
    page_area = page.rect.get_area()
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for image_info in page.get_image_info(xrefs=False):
        try:
            visible = pymupdf.Rect(image_info["bbox"]) & page.rect
            covered += max(0.0, visible.get_area())
        except (KeyError, TypeError, ValueError):
            continue
    return round(min(covered / page_area, 1.0), 4)


def calculate_visual_content_ratio(image: Image.Image, white_threshold: int = 245) -> float:
    grayscale = image.convert("L")
    total = grayscale.width * grayscale.height
    if total <= 0:
        return 0.0
    return round(sum(grayscale.histogram()[:white_threshold]) / total, 4)


def collect_page_evidence(
    page: pymupdf.Page,
    rendered_image: Image.Image,
    *,
    policy: PageClassificationPolicy,
) -> PageEvidence:
    native_text = normalize_ocr_text(page.get_text("text"))
    compact_length = len(re.sub(r"\s+", "", native_text))
    blocks: list[NativeTextBlock] = []
    for raw_block in page.get_text("blocks"):
        if len(raw_block) < 5:
            continue
        text = normalize_ocr_text(str(raw_block[4]))
        left, top, right, bottom = map(float, raw_block[:4])
        if text and left >= 0 and top >= 0 and right > left and bottom > top:
            blocks.append(NativeTextBlock((left, top, right, bottom), text))

    return PageEvidence(
        native_text=native_text,
        normalized_native_characters=compact_length,
        meaningful_character_ratio=round(_meaningful_ratio(native_text), 4),
        image_coverage=calculate_image_coverage(page),
        visual_content_ratio=calculate_visual_content_ratio(
            rendered_image,
            policy.white_pixel_threshold,
        ),
        native_blocks=tuple(blocks),
        page_width_points=float(page.rect.width),
        page_height_points=float(page.rect.height),
        rendered_width_pixels=rendered_image.width,
        rendered_height_pixels=rendered_image.height,
    )


def classify_page(
    evidence: PageEvidence,
    *,
    policy: PageClassificationPolicy,
    accepted_ocr_text: str = "",
) -> PageClassification:
    """Classify from text, PDF image, and rendered visual evidence."""
    usable_native = (
        evidence.normalized_native_characters >= policy.min_native_characters
        and evidence.meaningful_character_ratio >= policy.min_meaningful_character_ratio
        and bool(evidence.native_blocks)
    )
    some_native = evidence.normalized_native_characters >= policy.min_any_native_characters
    visual = evidence.visual_content_ratio >= policy.min_visual_content_ratio
    accepted_ocr = bool(normalize_ocr_text(accepted_ocr_text))

    if usable_native:
        if evidence.image_coverage >= policy.mixed_image_coverage and visual:
            return PageClassification(PageType.MIXED, ("usable_native_text", "substantial_image_content"), True)
        return PageClassification(PageType.DIGITAL, ("usable_native_text",), True)

    if some_native:
        if (
            evidence.visual_content_ratio >= policy.min_dense_visual_content_ratio
            or evidence.image_coverage >= policy.mixed_image_coverage
            or accepted_ocr
        ):
            return PageClassification(
                PageType.MIXED,
                ("limited_native_text", "additional_visual_or_ocr_evidence"),
                False,
            )
        return PageClassification(PageType.UNKNOWN, ("limited_native_text_without_scan_evidence",), False)

    if accepted_ocr:
        return PageClassification(PageType.SCANNED, ("accepted_ocr_without_usable_native_text",), False)
    if evidence.image_coverage >= policy.scanned_image_coverage and visual:
        return PageClassification(PageType.SCANNED, ("large_displayed_image", "visible_page_content"), False)
    if evidence.visual_content_ratio >= policy.min_dense_visual_content_ratio:
        return PageClassification(PageType.SCANNED, ("dense_rendered_content_without_native_text",), False)
    if evidence.visual_content_ratio <= policy.max_empty_visual_content_ratio:
        return PageClassification(PageType.EMPTY, ("no_native_or_visible_content",), False)
    if visual:
        return PageClassification(PageType.UNKNOWN, ("limited_visual_content_may_be_decorative",), False)
    return PageClassification(PageType.UNKNOWN, ("insufficient_classification_evidence",), False)
