from collections import defaultdict
from dataclasses import dataclass
from dataclasses import replace
from statistics import fmean

import pytesseract
from PIL import Image
from PIL import ImageDraw
from pytesseract import Output

from eda.ocr import OCR_TIMEOUT


MIN_SINGLE_WORD_CONFIDENCE = 50.0
DEFAULT_REGION_PADDING = 18


@dataclass(frozen=True)
class OCRRegion:
    region_id: int
    block_number: int

    left: int
    top: int
    right: int
    bottom: int

    word_count: int
    probe_confidence: float | None
    probe_text: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (
            self.left,
            self.top,
            self.right,
            self.bottom,
        )


def parse_confidence(
    raw_confidence,
) -> float | None:
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        return None

    if confidence < 0:
        return None

    return confidence


def expand_box(
    left: int,
    top: int,
    right: int,
    bottom: int,
    image_width: int,
    image_height: int,
    padding: int,
) -> tuple[int, int, int, int]:
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image_width, right + padding),
        min(image_height, bottom + padding),
    )


def region_sort_key(
    region: OCRRegion,
    row_step: int,
    direction: str,
) -> tuple[int, int]:
    row_number = round(
        region.top / row_step
    )

    if direction == "rtl":
        horizontal_position = -region.right
    else:
        horizontal_position = region.left

    return (
        row_number,
        horizontal_position,
    )


def detect_text_regions(
    image: Image.Image,
    languages: str = "fas+eng",
    psm: int = 3,
    direction: str = "rtl",
    padding: int = DEFAULT_REGION_PADDING,
    timeout: int = OCR_TIMEOUT,
) -> list[OCRRegion]:
    config = f"--oem 1 --psm {psm}"

    data = pytesseract.image_to_data(
        image,
        lang=languages,
        config=config,
        output_type=Output.DICT,
        timeout=timeout,
    )

    grouped_words: dict[int, list[dict]] = (
        defaultdict(list)
    )

    item_count = len(data["text"])

    for index in range(item_count):
        word = data["text"][index].strip()

        if not word:
            continue

        block_number = int(
            data["block_num"][index]
        )

        if block_number <= 0:
            continue

        confidence = parse_confidence(
            data["conf"][index]
        )

        if confidence is None:
            continue

        left = int(data["left"][index])
        top = int(data["top"][index])
        width = int(data["width"][index])
        height = int(data["height"][index])

        if width <= 0 or height <= 0:
            continue

        grouped_words[block_number].append({
            "text": word,
            "confidence": confidence,
            "left": left,
            "top": top,
            "right": left + width,
            "bottom": top + height,
        })

    candidates = []

    for block_number, words in grouped_words.items():
        confidences = [
            item["confidence"]
            for item in words
        ]

        mean_confidence = (
            fmean(confidences)
            if confidences
            else None
        )

        # ناحیه تک‌کلمه‌ای فقط وقتی نگه داشته
        # می‌شود که Confidence قابل‌قبولی داشته باشد.
        if (
            len(words) == 1
            and (
                mean_confidence is None
                or mean_confidence
                < MIN_SINGLE_WORD_CONFIDENCE
            )
        ):
            continue

        raw_left = min(
            item["left"]
            for item in words
        )
        raw_top = min(
            item["top"]
            for item in words
        )
        raw_right = max(
            item["right"]
            for item in words
        )
        raw_bottom = max(
            item["bottom"]
            for item in words
        )

        (
            left,
            top,
            right,
            bottom,
        ) = expand_box(
            left=raw_left,
            top=raw_top,
            right=raw_right,
            bottom=raw_bottom,
            image_width=image.width,
            image_height=image.height,
            padding=padding,
        )

        probe_text = " ".join(
            item["text"]
            for item in words
        )

        candidates.append(
            OCRRegion(
                region_id=0,
                block_number=block_number,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                word_count=len(words),
                probe_confidence=mean_confidence,
                probe_text=probe_text,
            )
        )

    # تقریباً یک درصد ارتفاع صفحه برای
    # تشخیص ناحیه‌هایی که در یک ردیف‌اند.
    row_step = max(
        20,
        image.height // 100,
    )

    candidates.sort(
        key=lambda region: region_sort_key(
            region,
            row_step=row_step,
            direction=direction,
        )
    )

    return [
        replace(
            region,
            region_id=index,
        )
        for index, region in enumerate(
            candidates,
            start=1,
        )
    ]


def crop_region(
    image: Image.Image,
    region: OCRRegion,
) -> Image.Image:
    return image.crop(
        region.box
    )


def draw_regions(
    image: Image.Image,
    regions: list[OCRRegion],
) -> Image.Image:
    canvas = image.convert("RGB")
    draw = ImageDraw.Draw(canvas)

    colors = (
        "#e53935",
        "#1e88e5",
        "#43a047",
        "#8e24aa",
        "#fb8c00",
        "#00897b",
    )

    for region in regions:
        color = colors[
            (region.region_id - 1)
            % len(colors)
        ]

        draw.rectangle(
            region.box,
            outline=color,
            width=5,
        )

        label = str(region.region_id)

        label_left = region.left
        label_top = max(
            0,
            region.top - 24,
        )

        label_box = (
            label_left,
            label_top,
            label_left + 34,
            label_top + 24,
        )

        draw.rectangle(
            label_box,
            fill=color,
        )

        draw.text(
            (
                label_left + 9,
                label_top + 4,
            ),
            label,
            fill="white",
        )

    return canvas

def get_horizontal_overlap(
    first: OCRRegion,
    second: OCRRegion,
) -> int:
    return max(
        0,
        min(first.right, second.right)
        - max(first.left, second.left),
    )

def expand_regions_vertically(
    regions: list[OCRRegion],
    image_height: int,
    vertical_padding: int,
) -> list[OCRRegion]:
    return [
        replace(
            region,
            top=max(
                0,
                region.top - vertical_padding,
            ),
            bottom=min(
                image_height,
                region.bottom + vertical_padding,
            ),
        )
        for region in regions
    ]

def get_vertical_overlap(
    first: OCRRegion,
    second: OCRRegion,
) -> int:
    return max(
        0,
        min(first.bottom, second.bottom)
        - max(first.top, second.top),
    )


def should_merge_regions(
    first: OCRRegion,
    second: OCRRegion,
    min_horizontal_overlap_ratio: float = 0.60,
) -> bool:
    vertical_overlap = get_vertical_overlap(
        first,
        second,
    )

    if vertical_overlap <= 0:
        return False

    minimum_width = min(
        first.width,
        second.width,
    )

    if minimum_width <= 0:
        return False

    horizontal_overlap = get_horizontal_overlap(
        first,
        second,
    )

    overlap_ratio = (
        horizontal_overlap
        / minimum_width
    )

    return (
        overlap_ratio
        >= min_horizontal_overlap_ratio
    )


def merge_region_group(
    regions: list[OCRRegion],
) -> OCRRegion:
    ordered_regions = sorted(
        regions,
        key=lambda region: region.region_id,
    )

    total_word_count = sum(
        region.word_count
        for region in ordered_regions
    )

    confidence_items = [
        region
        for region in ordered_regions
        if region.probe_confidence is not None
    ]

    confidence_weight = sum(
        max(1, region.word_count)
        for region in confidence_items
    )

    if confidence_weight:
        probe_confidence = sum(
            region.probe_confidence
            * max(1, region.word_count)
            for region in confidence_items
        ) / confidence_weight
    else:
        probe_confidence = None

    probe_text = " ".join(
        region.probe_text.strip()
        for region in ordered_regions
        if region.probe_text.strip()
    )

    return OCRRegion(
        region_id=0,
        block_number=min(
            region.block_number
            for region in ordered_regions
        ),
        left=min(
            region.left
            for region in ordered_regions
        ),
        top=min(
            region.top
            for region in ordered_regions
        ),
        right=max(
            region.right
            for region in ordered_regions
        ),
        bottom=max(
            region.bottom
            for region in ordered_regions
        ),
        word_count=total_word_count,
        probe_confidence=probe_confidence,
        probe_text=probe_text,
    )


def merge_overlapping_regions(
    regions: list[OCRRegion],
    row_step: int,
    direction: str = "rtl",
    min_horizontal_overlap_ratio: float = 0.60,
) -> list[OCRRegion]:
    if not regions:
        return []

    parents = list(
        range(len(regions))
    )

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[
                parents[index]
            ]
            index = parents[index]

        return index

    def union(
        first_index: int,
        second_index: int,
    ) -> None:
        first_root = find(first_index)
        second_root = find(second_index)

        if first_root != second_root:
            parents[second_root] = first_root

    for first_index, first in enumerate(
        regions
    ):
        for second_index in range(
            first_index + 1,
            len(regions),
        ):
            second = regions[second_index]

            if should_merge_regions(
                first,
                second,
                min_horizontal_overlap_ratio=(
                    min_horizontal_overlap_ratio
                ),
            ):
                union(
                    first_index,
                    second_index,
                )

    grouped_regions = {}

    for index, region in enumerate(regions):
        root = find(index)

        grouped_regions.setdefault(
            root,
            [],
        ).append(region)

    merged_regions = [
        merge_region_group(group)
        for group in grouped_regions.values()
    ]

    merged_regions.sort(
        key=lambda region: region_sort_key(
            region,
            row_step=row_step,
            direction=direction,
        )
    )

    return [
        replace(
            region,
            region_id=index,
        )
        for index, region in enumerate(
            merged_regions,
            start=1,
        )
    ]
