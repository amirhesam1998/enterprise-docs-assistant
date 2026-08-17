from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import cv2
import fitz
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output


# Tesseract is normally discovered through PATH. On Windows, set
# TESSERACT_CMD when the executable is installed somewhere else.
_TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if _TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD


MIN_NATIVE_TEXT_LENGTH = 40
MIN_OCR_CONFIDENCE = 55.0
MIN_QUALITY_SCORE = 55.0
MIN_OCR_AGREEMENT = 55.0
COMPLEX_LAYOUT_MIN_REGIONS = 3
REGION_ROUTE_TOLERANCE = 12.0
MAX_VERTICAL_PADDING = 90


@dataclass
class OCRCandidate:
    text: str
    confidence: float
    quality_score: float
    psm: int
    languages: str
    preprocess: str
    words_count: int
    agreement_score: float = 0.0
    selection_score: float = 0.0


@dataclass
class RegionResult:
    region: int
    box: list[int]
    selected_psm: Optional[int]
    selected_languages: Optional[str]
    selected_preprocess: Optional[str]
    confidence: float
    quality_score: float
    agreement_score: float
    selection_score: float
    words_count: int
    accepted: bool
    text: str


def normalize_text(text: str) -> str:
    if not text:
        return ""

    replacements = {
        "\u200c": " ",
        "\u200d": "",
        "\ufeff": "",
        "\u00ad": "",
        "\xa0": " ",
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
    }

    for source, target in replacements.items():
        text = text.replace(source, target)

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def calculate_text_quality(
    text: str,
    confidence: Optional[float] = None,
) -> float:
    compact = re.sub(r"\s+", "", normalize_text(text))

    if not compact:
        return 0.0

    characters_count = len(compact)
    words = re.findall(r"\S+", normalize_text(text))

    alphanumeric_count = sum(
        character.isalnum()
        for character in compact
    )

    valid_punctuation = set(
        ".,،؛:!?؟()[]{}-_/@%+*=<>«»'\""
    )

    valid_characters_count = sum(
        character.isalnum()
        or character in valid_punctuation
        for character in compact
    )

    suspicious_characters_count = sum(
        character in {"�", "□", "■", "◆"}
        for character in compact
    )

    alphanumeric_ratio = (
        alphanumeric_count / characters_count
    )

    valid_character_ratio = (
        valid_characters_count / characters_count
    )

    suspicious_ratio = (
        suspicious_characters_count / characters_count
    )

    length_score = min(characters_count / 250, 1.0)
    words_score = min(len(words) / 35, 1.0)

    base_score = (
        alphanumeric_ratio * 35
        + valid_character_ratio * 25
        + length_score * 20
        + words_score * 20
    )

    base_score -= suspicious_ratio * 100

    # Excessive repetition is often a sign of broken OCR.
    if words:
        normalized_words = [
            re.sub(
                r"[^\w\u0600-\u06FF]+",
                "",
                word,
            ).lower()
            for word in words
        ]

        normalized_words = [
            word
            for word in normalized_words
            if word
        ]

        if normalized_words:
            unique_ratio = (
                len(set(normalized_words))
                / len(normalized_words)
            )

            if unique_ratio < 0.25:
                base_score -= 15

    base_score = max(
        0.0,
        min(100.0, base_score),
    )

    if confidence is not None:
        bounded_confidence = max(
            0.0,
            min(100.0, confidence),
        )

        base_score = (
            base_score * 0.55
            + bounded_confidence * 0.45
        )

    return round(
        max(0.0, min(100.0, base_score)),
        2,
    )


def normalize_for_agreement(text: str) -> str:
    text = normalize_text(text).casefold()

    text = re.sub(
        r"[^\w\u0600-\u06FF]+",
        " ",
        text,
    )

    return " ".join(text.split())


def calculate_candidate_similarity(
    first_text: str,
    second_text: str,
) -> float:
    first = normalize_for_agreement(first_text)
    second = normalize_for_agreement(second_text)

    if not first or not second:
        return 0.0

    sequence_score = SequenceMatcher(
        None,
        first,
        second,
    ).ratio()

    first_tokens = set(first.split())
    second_tokens = set(second.split())

    token_overlap = (
        len(first_tokens & second_tokens)
        / max(
            1,
            min(
                len(first_tokens),
                len(second_tokens),
            ),
        )
    )

    return round(
        (
            sequence_score * 0.45
            + token_overlap * 0.55
        ) * 100,
        2,
    )


def calculate_candidate_consensus(
    candidates: list[OCRCandidate],
) -> None:
    if len(candidates) == 1:
        candidates[0].agreement_score = 100.0
        candidates[0].selection_score = round(
            candidates[0].quality_score * 0.40
            + candidates[0].confidence * 0.35
            + 100 * 0.25,
            2,
        )
        return

    for candidate in candidates:
        similarities = [
            calculate_candidate_similarity(
                candidate.text,
                other.text,
            )
            for other in candidates
            if other is not candidate
        ]

        similarities.sort(reverse=True)
        strongest_similarities = similarities[:3]

        agreement = (
            sum(strongest_similarities)
            / len(strongest_similarities)
            if strongest_similarities
            else 0.0
        )

        candidate.agreement_score = round(
            agreement,
            2,
        )

        candidate.selection_score = round(
            candidate.quality_score * 0.40
            + candidate.confidence * 0.35
            + candidate.agreement_score * 0.25,
            2,
        )


def candidate_route_score(
    candidate: Optional[OCRCandidate],
) -> float:
    if candidate is None:
        return 0.0

    return round(
        candidate.quality_score * 0.40
        + candidate.confidence * 0.35
        + candidate.agreement_score * 0.25,
        2,
    )


def render_page(
    page: fitz.Page,
    dpi: int,
) -> np.ndarray:
    zoom = dpi / 72

    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(zoom, zoom),
        alpha=False,
    )

    image = np.frombuffer(
        pixmap.samples,
        dtype=np.uint8,
    ).reshape(
        pixmap.height,
        pixmap.width,
        pixmap.n,
    )

    if pixmap.n == 4:
        image = cv2.cvtColor(
            image,
            cv2.COLOR_RGBA2RGB,
        )

    return image


def preprocess_image(
    image: np.ndarray,
    mode: str,
) -> np.ndarray:
    if mode == "raw":
        return image

    if mode != "enhanced":
        raise ValueError(
            f"Unknown preprocessing mode: {mode}"
        )

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_RGB2GRAY,
    )

    gray = cv2.fastNlMeansDenoising(
        gray,
        None,
        h=10,
        templateWindowSize=7,
        searchWindowSize=21,
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    gray = clahe.apply(gray)

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        35,
        15,
    )

    return cv2.cvtColor(
        binary,
        cv2.COLOR_GRAY2RGB,
    )


def resolve_languages(
    language_profiles: list[str],
) -> list[str]:
    installed_languages = set(
        pytesseract.get_languages(config="")
    )

    valid_profiles: list[str] = []

    for profile in language_profiles:
        requested_languages = profile.split("+")

        if all(
            language in installed_languages
            for language in requested_languages
        ):
            valid_profiles.append(profile)

    if valid_profiles:
        return valid_profiles

    if "eng" in installed_languages:
        print(
            "Warning: requested OCR language profiles are "
            "not installed; falling back to eng."
        )
        return ["eng"]

    raise RuntimeError(
        "No compatible Tesseract language model is installed."
    )


def run_ocr(
    image: np.ndarray,
    psm: int,
    languages: str,
    preprocess: str,
) -> OCRCandidate:
    prepared_image = preprocess_image(
        image,
        preprocess,
    )

    pil_image = Image.fromarray(prepared_image)
    config = f"--oem 1 --psm {psm}"

    text = pytesseract.image_to_string(
        pil_image,
        lang=languages,
        config=config,
    )

    data = pytesseract.image_to_data(
        pil_image,
        lang=languages,
        config=config,
        output_type=Output.DICT,
    )

    confidences: list[float] = []

    for raw_confidence, word in zip(
        data["conf"],
        data["text"],
    ):
        word = str(word).strip()

        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            continue

        if word and confidence >= 0:
            confidences.append(confidence)

    average_confidence = (
        sum(confidences) / len(confidences)
        if confidences
        else 0.0
    )

    text = normalize_text(text)

    return OCRCandidate(
        text=text,
        confidence=round(
            average_confidence,
            2,
        ),
        quality_score=calculate_text_quality(
            text,
            average_confidence,
        ),
        psm=psm,
        languages=languages,
        preprocess=preprocess,
        words_count=len(
            re.findall(r"\S+", text)
        ),
    )


def select_best_ocr_candidate(
    image: np.ndarray,
    language_profiles: list[str],
    psm_values: tuple[int, ...] = (6, 11),
    preprocess_modes: tuple[str, ...] = (
        "raw",
        "enhanced",
    ),
) -> tuple[
    Optional[OCRCandidate],
    list[OCRCandidate],
]:
    candidates: list[OCRCandidate] = []

    for languages in language_profiles:
        for psm in psm_values:
            for preprocess in preprocess_modes:
                try:
                    candidate = run_ocr(
                        image=image,
                        psm=psm,
                        languages=languages,
                        preprocess=preprocess,
                    )
                    candidates.append(candidate)

                except pytesseract.TesseractError:
                    continue

    if not candidates:
        return None, []

    calculate_candidate_consensus(candidates)

    candidates.sort(
        key=lambda candidate: (
            candidate.selection_score,
            candidate.quality_score,
            candidate.confidence,
            len(candidate.text),
        ),
        reverse=True,
    )

    return candidates[0], candidates


def calculate_image_coverage(
    page: fitz.Page,
) -> float:
    page_area = page.rect.get_area()

    if page_area <= 0:
        return 0.0

    covered_area = 0.0

    for image in page.get_images(full=True):
        xref = image[0]

        try:
            rectangles = page.get_image_rects(xref)
        except Exception:
            continue

        for rectangle in rectangles:
            covered_area += rectangle.get_area()

    return round(
        min(covered_area / page_area, 1.0),
        4,
    )


def classify_page(
    native_text: str,
    native_score: float,
    image_coverage: float,
) -> str:
    text_length = len(
        re.sub(r"\s+", "", native_text)
    )

    if text_length < 5:
        if image_coverage >= 0.02:
            return "scanned"

        return "empty"

    if (
        text_length >= MIN_NATIVE_TEXT_LENGTH
        and native_score >= 60
    ):
        if image_coverage >= 0.25:
            return "mixed"

        return "digital"

    if image_coverage >= 0.15:
        return "mixed"

    if native_score < 60:
        return "mixed"

    return "digital"


def boxes_overlap(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second

    intersection_width = max(
        0,
        min(ax2, bx2) - max(ax1, bx1),
    )

    intersection_height = max(
        0,
        min(ay2, by2) - max(ay1, by1),
    )

    if (
        intersection_width <= 0
        or intersection_height <= 0
    ):
        return False

    first_area = max(
        1,
        (ax2 - ax1) * (ay2 - ay1),
    )

    second_area = max(
        1,
        (bx2 - bx1) * (by2 - by1),
    )

    intersection_area = (
        intersection_width
        * intersection_height
    )

    return (
        intersection_area
        / min(first_area, second_area)
    ) >= 0.15


def should_merge_boxes(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    if boxes_overlap(first, second):
        return True

    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second

    horizontal_overlap = max(
        0,
        min(ax2, bx2) - max(ax1, bx1),
    )

    minimum_width = max(
        1,
        min(ax2 - ax1, bx2 - bx1),
    )

    horizontal_overlap_ratio = (
        horizontal_overlap / minimum_width
    )

    vertical_gap = max(
        0,
        max(ay1, by1) - min(ay2, by2),
    )

    maximum_allowed_gap = max(
        35,
        int(
            min(
                ay2 - ay1,
                by2 - by1,
            ) * 0.8
        ),
    )

    return (
        horizontal_overlap_ratio >= 0.30
        and vertical_gap <= maximum_allowed_gap
    )


def merge_detected_boxes(
    boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    boxes = boxes[:]
    changed = True

    while changed:
        changed = False
        merged_boxes: list[
            tuple[int, int, int, int]
        ] = []
        used = [False] * len(boxes)

        for index, current_box in enumerate(boxes):
            if used[index]:
                continue

            x1, y1, x2, y2 = current_box
            used[index] = True

            for other_index in range(
                index + 1,
                len(boxes),
            ):
                if used[other_index]:
                    continue

                other_box = boxes[other_index]

                if should_merge_boxes(
                    (x1, y1, x2, y2),
                    other_box,
                ):
                    ox1, oy1, ox2, oy2 = other_box

                    x1 = min(x1, ox1)
                    y1 = min(y1, oy1)
                    x2 = max(x2, ox2)
                    y2 = max(y2, oy2)

                    used[other_index] = True
                    changed = True

            merged_boxes.append(
                (x1, y1, x2, y2)
            )

        boxes = merged_boxes

    return boxes


def detect_text_regions(
    image: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_RGB2GRAY,
    )

    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        15,
    )

    image_height, image_width = gray.shape

    horizontal_kernel_width = max(
        20,
        image_width // 90,
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (horizontal_kernel_width, 3),
    )

    connected = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        horizontal_kernel,
    )

    connected = cv2.dilate(
        connected,
        np.ones(
            (7, 7),
            dtype=np.uint8,
        ),
        iterations=1,
    )

    contours, _ = cv2.findContours(
        connected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    boxes: list[
        tuple[int, int, int, int]
    ] = []

    minimum_area = (
        image_width
        * image_height
        * 0.00015
    )

    for contour in contours:
        x, y, width, height = cv2.boundingRect(
            contour
        )
        area = width * height

        if area < minimum_area:
            continue

        if width < 45 or height < 14:
            continue

        if (
            width > image_width * 0.98
            and height > image_height * 0.95
        ):
            continue

        boxes.append(
            (x, y, x + width, y + height)
        )

    boxes = merge_detected_boxes(boxes)

    return sorted(
        boxes,
        key=lambda box: (
            box[1],
            -box[0],
        ),
    )


def count_meaningful_regions(
    boxes: list[tuple[int, int, int, int]],
    image_width: int,
    image_height: int,
) -> int:
    page_area = max(
        1,
        image_width * image_height,
    )

    count = 0

    for x1, y1, x2, y2 in boxes:
        region_area = max(
            0,
            (x2 - x1) * (y2 - y1),
        )

        coverage = region_area / page_area

        if 0.001 <= coverage <= 0.80:
            count += 1

    return count


def horizontal_overlap_ratio(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    ax1, _, ax2, _ = first
    bx1, _, bx2, _ = second

    overlap = max(
        0,
        min(ax2, bx2) - max(ax1, bx1),
    )

    minimum_width = max(
        1,
        min(ax2 - ax1, bx2 - bx1),
    )

    return overlap / minimum_width


def add_neighbor_aware_padding(
    boxes: list[tuple[int, int, int, int]],
    image_width: int,
    image_height: int,
) -> list[tuple[int, int, int, int]]:
    padded_boxes: list[
        tuple[int, int, int, int]
    ] = []

    for index, box in enumerate(boxes):
        x1, y1, x2, y2 = box

        upper_bound = 0
        lower_bound = image_height

        for other_index, other_box in enumerate(
            boxes
        ):
            if other_index == index:
                continue

            if (
                horizontal_overlap_ratio(
                    box,
                    other_box,
                ) < 0.20
            ):
                continue

            _, other_y1, _, other_y2 = other_box

            if other_y2 <= y1:
                upper_bound = max(
                    upper_bound,
                    other_y2,
                )

            if other_y1 >= y2:
                lower_bound = min(
                    lower_bound,
                    other_y1,
                )

        available_top_space = max(
            0,
            y1 - upper_bound,
        )

        available_bottom_space = max(
            0,
            lower_bound - y2,
        )

        top_padding = min(
            MAX_VERTICAL_PADDING,
            available_top_space // 2,
        )

        bottom_padding = min(
            MAX_VERTICAL_PADDING,
            available_bottom_space // 2,
        )

        horizontal_padding = min(
            30,
            max(12, (x2 - x1) // 40),
        )

        padded_boxes.append(
            (
                max(0, x1 - horizontal_padding),
                max(0, y1 - top_padding),
                min(
                    image_width,
                    x2 + horizontal_padding,
                ),
                min(
                    image_height,
                    y2 + bottom_padding,
                ),
            )
        )

    return padded_boxes


def is_duplicate_text(
    text: str,
    accepted_texts: list[str],
) -> bool:
    normalized_text = re.sub(
        r"\s+",
        " ",
        normalize_text(text),
    ).lower()

    if not normalized_text:
        return True

    for accepted_text in accepted_texts:
        normalized_accepted = re.sub(
            r"\s+",
            " ",
            normalize_text(accepted_text),
        ).lower()

        similarity = SequenceMatcher(
            None,
            normalized_text,
            normalized_accepted,
        ).ratio()

        if similarity >= 0.90:
            return True

    return False


def run_region_ocr(
    image: np.ndarray,
    language_profiles: list[str],
    detected_boxes: Optional[
        list[tuple[int, int, int, int]]
    ] = None,
) -> tuple[
    Optional[OCRCandidate],
    list[RegionResult],
]:
    if detected_boxes is None:
        detected_boxes = detect_text_regions(image)

    padded_boxes = add_neighbor_aware_padding(
        detected_boxes,
        image_width=image.shape[1],
        image_height=image.shape[0],
    )

    selected_texts: list[str] = []
    region_results: list[RegionResult] = []
    selected_candidates: list[OCRCandidate] = []

    for region_number, box in enumerate(
        padded_boxes,
        start=1,
    ):
        x1, y1, x2, y2 = box
        crop = image[y1:y2, x1:x2]

        selected_candidate, _ = (
            select_best_ocr_candidate(
                image=crop,
                language_profiles=language_profiles,
                psm_values=(6, 11),
                preprocess_modes=(
                    "raw",
                    "enhanced",
                ),
            )
        )

        if selected_candidate is None:
            region_results.append(
                RegionResult(
                    region=region_number,
                    box=list(box),
                    selected_psm=None,
                    selected_languages=None,
                    selected_preprocess=None,
                    confidence=0.0,
                    quality_score=0.0,
                    agreement_score=0.0,
                    selection_score=0.0,
                    words_count=0,
                    accepted=False,
                    text="",
                )
            )
            continue

        accepted = (
            selected_candidate.confidence >= 35
            and selected_candidate.quality_score >= 40
            and selected_candidate.words_count >= 1
        )

        region_results.append(
            RegionResult(
                region=region_number,
                box=list(box),
                selected_psm=selected_candidate.psm,
                selected_languages=(
                    selected_candidate.languages
                ),
                selected_preprocess=(
                    selected_candidate.preprocess
                ),
                confidence=(
                    selected_candidate.confidence
                ),
                quality_score=(
                    selected_candidate.quality_score
                ),
                agreement_score=(
                    selected_candidate.agreement_score
                ),
                selection_score=(
                    selected_candidate.selection_score
                ),
                words_count=(
                    selected_candidate.words_count
                ),
                accepted=accepted,
                text=selected_candidate.text,
            )
        )

        if not accepted:
            continue

        if not is_duplicate_text(
            selected_candidate.text,
            selected_texts,
        ):
            selected_texts.append(
                selected_candidate.text
            )
            selected_candidates.append(
                selected_candidate
            )

    final_text = normalize_text(
        "\n\n".join(selected_texts)
    )

    if not selected_candidates:
        return None, region_results

    total_words = sum(
        max(candidate.words_count, 1)
        for candidate in selected_candidates
    )

    weighted_confidence = sum(
        candidate.confidence
        * max(candidate.words_count, 1)
        for candidate in selected_candidates
    ) / total_words

    weighted_agreement = sum(
        candidate.agreement_score
        * max(candidate.words_count, 1)
        for candidate in selected_candidates
    ) / total_words

    selected_psm_values = {
        candidate.psm
        for candidate in selected_candidates
    }

    selected_language_values = {
        candidate.languages
        for candidate in selected_candidates
    }

    selected_preprocess_values = {
        candidate.preprocess
        for candidate in selected_candidates
    }

    combined_quality = calculate_text_quality(
        final_text,
        weighted_confidence,
    )

    combined_selection_score = (
        combined_quality * 0.40
        + weighted_confidence * 0.35
        + weighted_agreement * 0.25
    )

    combined_candidate = OCRCandidate(
        text=final_text,
        confidence=round(
            weighted_confidence,
            2,
        ),
        quality_score=round(
            combined_quality,
            2,
        ),
        psm=(
            selected_candidates[0].psm
            if len(selected_psm_values) == 1
            else -1
        ),
        languages=(
            selected_candidates[0].languages
            if len(selected_language_values) == 1
            else "mixed"
        ),
        preprocess=(
            selected_candidates[0].preprocess
            if len(selected_preprocess_values) == 1
            else "mixed"
        ),
        words_count=len(
            re.findall(r"\S+", final_text)
        ),
        agreement_score=round(
            weighted_agreement,
            2,
        ),
        selection_score=round(
            combined_selection_score,
            2,
        ),
    )

    return combined_candidate, region_results


def candidate_passes_quality_gate(
    candidate: Optional[OCRCandidate],
) -> bool:
    if candidate is None:
        return False

    return (
        candidate.confidence
        >= MIN_OCR_CONFIDENCE
        and candidate.quality_score
        >= MIN_QUALITY_SCORE
        and candidate.agreement_score
        >= MIN_OCR_AGREEMENT
        and len(candidate.text) >= 10
    )


def process_page(
    page: fitz.Page,
    page_number: int,
    dpi: int,
    language_profiles: list[str],
) -> tuple[dict, str]:
    started_at = time.perf_counter()

    native_text = normalize_text(
        page.get_text("text")
    )

    native_text_length = len(
        re.sub(r"\s+", "", native_text)
    )

    native_text_score = calculate_text_quality(
        native_text
    )

    image_coverage = calculate_image_coverage(page)

    page_type = classify_page(
        native_text=native_text,
        native_score=native_text_score,
        image_coverage=image_coverage,
    )

    selected_route = "native"
    selected_candidate: Optional[
        OCRCandidate
    ] = None
    final_text = native_text
    fallback_reasons: list[str] = []
    regions: list[RegionResult] = []
    full_page_candidates: list[
        OCRCandidate
    ] = []
    meaningful_regions_count = 0
    layout_is_complex = False
    full_page_score = 0.0
    region_score = 0.0

    if page_type != "digital":
        if native_text_length == 0:
            fallback_reasons.append(
                "native_text_is_empty"
            )
        elif native_text_score < 60:
            fallback_reasons.append(
                "native_text_quality_is_low"
            )
        elif page_type == "mixed":
            fallback_reasons.append(
                "page_contains_mixed_content"
            )

        page_image = render_page(page, dpi)

        detected_boxes = detect_text_regions(
            page_image
        )

        meaningful_regions_count = (
            count_meaningful_regions(
                detected_boxes,
                image_width=page_image.shape[1],
                image_height=page_image.shape[0],
            )
        )

        layout_is_complex = (
            meaningful_regions_count
            >= COMPLEX_LAYOUT_MIN_REGIONS
        )

        (
            full_page_candidate,
            full_page_candidates,
        ) = select_best_ocr_candidate(
            image=page_image,
            language_profiles=language_profiles,
            psm_values=(3, 4, 6, 11),
            preprocess_modes=(
                "raw",
                "enhanced",
            ),
        )

        full_page_passed = (
            candidate_passes_quality_gate(
                full_page_candidate
            )
        )

        if layout_is_complex:
            fallback_reasons.append(
                "complex_layout_detected"
            )

        if (
            full_page_candidate is not None
            and full_page_candidate.agreement_score
            < MIN_OCR_AGREEMENT
        ):
            fallback_reasons.append(
                "full_page_candidates_disagree"
            )

        should_run_region_ocr = (
            layout_is_complex
            or not full_page_passed
            or (
                full_page_candidate is not None
                and full_page_candidate.agreement_score
                < 70
            )
        )

        region_candidate: Optional[
            OCRCandidate
        ] = None

        if should_run_region_ocr:
            region_candidate, regions = (
                run_region_ocr(
                    image=page_image,
                    language_profiles=(
                        language_profiles
                    ),
                    detected_boxes=detected_boxes,
                )
            )

        region_is_usable = (
            region_candidate is not None
            and region_candidate.confidence >= 45
            and region_candidate.quality_score >= 50
            and len(region_candidate.text) >= 10
        )

        full_page_score = candidate_route_score(
            full_page_candidate
        )

        region_score = candidate_route_score(
            region_candidate
        )

        prefer_region = (
            region_is_usable
            and (
                not full_page_passed
                or (
                    layout_is_complex
                    and region_score
                    >= (
                        full_page_score
                        - REGION_ROUTE_TOLERANCE
                    )
                )
                or (
                    region_score
                    > full_page_score + 3
                )
            )
        )

        if prefer_region:
            selected_route = "region_ocr"
            selected_candidate = region_candidate
            final_text = region_candidate.text

            fallback_reasons.append(
                "region_ocr_selected"
            )

        elif full_page_candidate is not None:
            selected_route = "full_page_ocr"
            selected_candidate = (
                full_page_candidate
            )
            final_text = full_page_candidate.text

        elif region_candidate is not None:
            selected_route = "region_ocr"
            selected_candidate = region_candidate
            final_text = region_candidate.text

        elif native_text:
            selected_route = "native"
            final_text = native_text

        else:
            selected_route = "region_ocr"
            final_text = ""

    processing_time_ms = round(
        (
            time.perf_counter()
            - started_at
        ) * 1000,
        2,
    )

    if selected_route == "native":
        quality_gate_passed = (
            native_text_length
            >= MIN_NATIVE_TEXT_LENGTH
            and native_text_score >= 60
        )

        selected_psm = None
        selected_languages = None
        selected_preprocess = None
        ocr_confidence = None
        quality_score = native_text_score
        ocr_agreement_score = None
        selection_score = None

    else:
        quality_gate_passed = (
            candidate_passes_quality_gate(
                selected_candidate
            )
        )

        if selected_candidate is None:
            selected_psm = None
            selected_languages = None
            selected_preprocess = None
            ocr_confidence = 0.0
            quality_score = 0.0
            ocr_agreement_score = 0.0
            selection_score = 0.0
        else:
            selected_psm = (
                "mixed"
                if selected_candidate.psm == -1
                else selected_candidate.psm
            )
            selected_languages = (
                selected_candidate.languages
            )
            selected_preprocess = (
                selected_candidate.preprocess
            )
            ocr_confidence = (
                selected_candidate.confidence
            )
            quality_score = (
                selected_candidate.quality_score
            )
            ocr_agreement_score = (
                selected_candidate.agreement_score
            )
            selection_score = (
                selected_candidate.selection_score
            )

    report = {
        "page": page_number,
        "page_type": page_type,
        "native_text_length": native_text_length,
        "native_text_score": native_text_score,
        "image_coverage": image_coverage,
        "layout_regions_detected": (
            meaningful_regions_count
        ),
        "layout_is_complex": layout_is_complex,
        "selected_route": selected_route,
        "selected_psm": selected_psm,
        "selected_languages": selected_languages,
        "selected_preprocess": selected_preprocess,
        "ocr_confidence": ocr_confidence,
        "quality_score": quality_score,
        "ocr_agreement_score": (
            ocr_agreement_score
        ),
        "selection_score": selection_score,
        "full_page_route_score": (
            full_page_score
        ),
        "region_route_score": region_score,
        "quality_gate_passed": (
            quality_gate_passed
        ),
        "fallback_reason": (
            "; ".join(fallback_reasons)
            if fallback_reasons
            else None
        ),
        "regions_count": len(regions),
        "processing_time_ms": (
            processing_time_ms
        ),
        "full_page_candidates": [
            {
                "psm": candidate.psm,
                "languages": (
                    candidate.languages
                ),
                "preprocess": (
                    candidate.preprocess
                ),
                "confidence": (
                    candidate.confidence
                ),
                "quality_score": (
                    candidate.quality_score
                ),
                "agreement_score": (
                    candidate.agreement_score
                ),
                "selection_score": (
                    candidate.selection_score
                ),
                "words_count": (
                    candidate.words_count
                ),
                "text_preview": (
                    candidate.text[:500]
                ),
            }
            for candidate in full_page_candidates
        ],
        "regions": [
            asdict(region)
            for region in regions
        ],
    }

    return report, normalize_text(final_text)


def parse_pages(value: str) -> list[int]:
    pages: list[int] = []

    for item in value.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            page = int(item)
        except ValueError as error:
            raise ValueError(
                f"Invalid page number: {item}"
            ) from error

        if page < 1:
            raise ValueError(
                "Page numbers must start from 1."
            )

        if page not in pages:
            pages.append(page)

    if not pages:
        raise ValueError(
            "At least one page number is required."
        )

    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Route PDF pages through native text, "
            "full-page OCR, or region OCR."
        )
    )

    parser.add_argument(
        "pdf_path",
        type=Path,
    )

    parser.add_argument(
        "--pages",
        required=True,
        help=(
            "One-based page numbers, for example: "
            "4,12"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "data/debug/ocr-router"
        ),
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=220,
    )

    parser.add_argument(
        "--languages",
        default="fas+eng",
        help=(
            "Comma-separated Tesseract profiles, "
            "for example: fas+eng,eng"
        ),
    )

    return parser


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if not arguments.pdf_path.is_file():
        parser.error(
            f"PDF file does not exist: "
            f"{arguments.pdf_path}"
        )

    if arguments.dpi < 72:
        parser.error(
            "--dpi must be at least 72."
        )

    try:
        requested_pages = parse_pages(
            arguments.pages
        )
    except ValueError as error:
        parser.error(str(error))

    requested_profiles = [
        profile.strip()
        for profile in (
            arguments.languages.split(",")
        )
        if profile.strip()
    ]

    if not requested_profiles:
        parser.error(
            "At least one OCR language profile "
            "is required."
        )

    language_profiles = resolve_languages(
        requested_profiles
    )

    arguments.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    document = fitz.open(arguments.pdf_path)

    try:
        for page_number in requested_pages:
            page_index = page_number - 1

            if page_index >= document.page_count:
                print(
                    f"Page {page_number} does not exist."
                )
                continue

            page = document.load_page(page_index)

            report, final_text = process_page(
                page=page,
                page_number=page_number,
                dpi=arguments.dpi,
                language_profiles=(
                    language_profiles
                ),
            )

            page_output_directory = (
                arguments.output_dir
                / f"page-{page_number}"
            )

            page_output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            report_path = (
                page_output_directory
                / "decision.json"
            )

            text_path = (
                page_output_directory
                / "final-text.txt"
            )

            report_path.write_text(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            text_path.write_text(
                final_text,
                encoding="utf-8",
            )

            print(f"\nPage: {page_number}")
            print(
                f"Page type: "
                f"{report['page_type']}"
            )
            print(
                f"Selected route: "
                f"{report['selected_route']}"
            )
            print(
                f"Layout regions: "
                f"{report['layout_regions_detected']}"
            )
            print(
                f"Layout is complex: "
                f"{report['layout_is_complex']}"
            )
            print(
                f"OCR confidence: "
                f"{report['ocr_confidence']}"
            )
            print(
                f"OCR agreement: "
                f"{report['ocr_agreement_score']}"
            )
            print(
                f"Quality score: "
                f"{report['quality_score']}"
            )
            print(
                f"Selection score: "
                f"{report['selection_score']}"
            )
            print(
                f"Quality gate passed: "
                f"{report['quality_gate_passed']}"
            )
            print(
                f"Fallback reason: "
                f"{report['fallback_reason']}"
            )
            print(f"Report: {report_path}")
            print(f"Text: {text_path}")

    finally:
        document.close()


if __name__ == "__main__":
    main()
