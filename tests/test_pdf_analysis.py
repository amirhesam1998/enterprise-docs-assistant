from __future__ import annotations

from eda.adaptive_ocr import order_region_boxes, sanitize_region_boxes
from eda.ingestion_schema import PageType
from eda.pdf_analysis import (
    NativeTextBlock,
    PageClassificationPolicy,
    PageEvidence,
    classify_page,
)


POLICY = PageClassificationPolicy()
LONG_TEXT = "This is synthetic native document text with enough meaningful characters for classification."


def evidence(text="", image_coverage=0.0, visual=0.0, blocks=()):
    compact = "".join(text.split())
    meaningful = sum(char.isalnum() for char in compact) / len(compact) if compact else 0.0
    return PageEvidence(
        native_text=text,
        normalized_native_characters=len(compact),
        meaningful_character_ratio=meaningful,
        image_coverage=image_coverage,
        visual_content_ratio=visual,
        native_blocks=blocks,
        page_width_points=600,
        page_height_points=800,
        rendered_width_pixels=1200,
        rendered_height_pixels=1600,
    )


def test_decorative_image_does_not_make_native_page_scanned():
    result = classify_page(
        evidence(
            LONG_TEXT,
            image_coverage=0.05,
            visual=0.02,
            blocks=(NativeTextBlock((10, 10, 500, 100), LONG_TEXT),),
        ),
        policy=POLICY,
    )
    assert result.page_type == PageType.DIGITAL


def test_few_native_characters_do_not_make_page_digital():
    result = classify_page(evidence("abc", visual=0.005), policy=POLICY)
    assert result.page_type == PageType.UNKNOWN


def test_decorative_visual_without_text_is_not_assumed_scanned():
    result = classify_page(evidence(image_coverage=0.05, visual=0.02), policy=POLICY)
    assert result.page_type == PageType.UNKNOWN


def test_scanned_mixed_and_empty_classification():
    scanned = classify_page(evidence(image_coverage=0.9, visual=0.08), policy=POLICY)
    mixed = classify_page(
        evidence(
            LONG_TEXT,
            image_coverage=0.5,
            visual=0.08,
            blocks=(NativeTextBlock((10, 10, 500, 100), LONG_TEXT),),
        ),
        policy=POLICY,
    )
    empty = classify_page(evidence(), policy=POLICY)
    assert (scanned.page_type, mixed.page_type, empty.page_type) == (
        PageType.SCANNED,
        PageType.MIXED,
        PageType.EMPTY,
    )


def test_accepted_ocr_refines_unknown_page_to_scanned():
    result = classify_page(evidence(visual=0.005), policy=POLICY, accepted_ocr_text=LONG_TEXT)
    assert result.page_type == PageType.SCANNED


def test_region_boxes_are_clamped_deduplicated_and_rtl_column_ordered():
    boxes = sanitize_region_boxes(
        [
            (-5, 10, 45, 80),
            (0, 10, 45, 80),
            (700, 20, 950, 100),
            (700, 120, 950, 200),
            (50, 20, 300, 100),
            (50, 120, 300, 200),
            (20, 20, 20, 40),
        ],
        page_width=1000,
        page_height=1200,
    )
    ordered = order_region_boxes(boxes, page_width=1000, direction="rtl")
    assert all(0 <= left < right <= 1000 and 0 <= top < bottom <= 1200 for left, top, right, bottom in ordered)
    assert ordered.index((700, 20, 950, 100)) < ordered.index((50, 20, 300, 100))
    assert ordered.index((700, 120, 950, 200)) < ordered.index((50, 20, 300, 100))
