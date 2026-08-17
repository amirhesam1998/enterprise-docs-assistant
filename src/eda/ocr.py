import os
from dataclasses import dataclass
from statistics import fmean
from typing import Literal

import pymupdf
import pytesseract
from PIL import Image
from PIL import ImageFilter
from PIL import ImageOps
from pytesseract import Output


OCR_DPI = 300
OCR_LANGUAGES = "fas+eng"
OCR_TIMEOUT = 120
LOW_CONFIDENCE_THRESHOLD = 60.0

PreprocessMode = Literal[
    "original",
    "enhanced",
    "binary",
]


@dataclass(frozen=True)
class OCRResult:
    text: str
    mean_confidence: float | None
    word_count: int
    low_confidence_words: tuple[str, ...]


def configure_tesseract() -> None:
    tesseract_cmd = os.getenv("TESSERACT_CMD")

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = (
            tesseract_cmd
        )


def validate_ocr_languages(
    languages: str = OCR_LANGUAGES,
) -> None:
    try:
        available_languages = set(
            pytesseract.get_languages(config="")
        )
    except pytesseract.TesseractNotFoundError:
        raise SystemExit(
            "Tesseract was not found. "
            "Install it or set TESSERACT_CMD."
        )

    requested_languages = set(
        languages.split("+")
    )

    missing_languages = (
        requested_languages - available_languages
    )

    if missing_languages:
        missing_label = ", ".join(
            sorted(missing_languages)
        )

        raise SystemExit(
            f"Missing Tesseract languages: "
            f"{missing_label}"
        )


def render_page_for_ocr(
    page: pymupdf.Page,
) -> Image.Image:
    pixmap = page.get_pixmap(
        dpi=OCR_DPI,
        colorspace=pymupdf.csRGB,
        alpha=False,
    )

    return Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )


def get_grayscale_median(
    image: Image.Image,
) -> int:
    histogram = image.histogram()
    middle = sum(histogram) / 2

    total = 0

    for value, count in enumerate(histogram):
        total += count

        if total >= middle:
            return value

    return 255


def prepare_grayscale(
    image: Image.Image,
) -> Image.Image:
    grayscale = ImageOps.grayscale(image)

    # Tesseract با متن تیره روی زمینه روشن
    # عملکرد بهتری دارد.
    if get_grayscale_median(grayscale) < 128:
        grayscale = ImageOps.invert(grayscale)

    grayscale = ImageOps.autocontrast(
        grayscale,
        cutoff=1,
    )

    return grayscale.filter(
        ImageFilter.UnsharpMask(
            radius=1,
            percent=150,
            threshold=3,
        )
    )


def calculate_otsu_threshold(
    image: Image.Image,
) -> int:
    histogram = image.histogram()
    pixel_count = sum(histogram)

    if pixel_count <= 0:
        return 127

    total_intensity = sum(
        value * count
        for value, count in enumerate(histogram)
    )

    background_count = 0
    background_intensity = 0

    best_variance = -1.0
    best_threshold = 127

    for value, count in enumerate(histogram):
        background_count += count

        if background_count == 0:
            continue

        foreground_count = (
            pixel_count - background_count
        )

        if foreground_count == 0:
            break

        background_intensity += value * count

        background_mean = (
            background_intensity
            / background_count
        )

        foreground_mean = (
            total_intensity
            - background_intensity
        ) / foreground_count

        variance = (
            background_count
            * foreground_count
            * (
                background_mean
                - foreground_mean
            ) ** 2
        )

        if variance > best_variance:
            best_variance = variance
            best_threshold = value

    return best_threshold


def preprocess_for_ocr(
    image: Image.Image,
    mode: PreprocessMode,
) -> Image.Image:
    if mode == "original":
        return image.copy()

    enhanced = prepare_grayscale(image)

    if mode == "enhanced":
        return enhanced

    if mode == "binary":
        threshold = calculate_otsu_threshold(
            enhanced
        )

        return enhanced.point(
            lambda value: (
                0
                if value <= threshold
                else 255
            )
        )

    raise ValueError(
        f"Unsupported preprocess mode: {mode}"
    )


def reconstruct_text(
    data: dict,
) -> str:
    lines = []
    current_words = []

    current_line_key = None
    previous_block_key = None

    item_count = len(data["text"])

    for index in range(item_count):
        word = data["text"][index].strip()

        if not word:
            continue

        block_key = (
            data["page_num"][index],
            data["block_num"][index],
        )

        line_key = (
            data["page_num"][index],
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )

        if line_key != current_line_key:
            if current_words:
                lines.append(
                    " ".join(current_words)
                )
                current_words = []

            if (
                previous_block_key is not None
                and block_key
                != previous_block_key
            ):
                lines.append("")

            current_line_key = line_key
            previous_block_key = block_key

        current_words.append(word)

    if current_words:
        lines.append(
            " ".join(current_words)
        )

    return "\n".join(lines).strip()


def run_ocr(
    image: Image.Image,
    languages: str = OCR_LANGUAGES,
    psm: int = 3,
) -> OCRResult:
    config = f"--oem 1 --psm {psm}"

    data = pytesseract.image_to_data(
        image,
        lang=languages,
        config=config,
        output_type=Output.DICT,
        timeout=OCR_TIMEOUT,
    )

    confidences = []
    low_confidence_words = []

    for raw_word, raw_confidence in zip(
        data["text"],
        data["conf"],
    ):
        word = raw_word.strip()

        if not word:
            continue

        try:
            confidence = float(
                raw_confidence
            )
        except (TypeError, ValueError):
            continue

        if confidence < 0:
            continue

        confidences.append(confidence)

        if (
            confidence
            < LOW_CONFIDENCE_THRESHOLD
        ):
            low_confidence_words.append(
                f"{word} ({confidence:.0f})"
            )

    if confidences:
        mean_confidence = fmean(
            confidences
        )
    else:
        mean_confidence = None

    return OCRResult(
        text=reconstruct_text(data),
        mean_confidence=mean_confidence,
        word_count=len(confidences),
        low_confidence_words=tuple(
            low_confidence_words
        ),
    )