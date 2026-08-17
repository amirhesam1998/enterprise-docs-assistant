import argparse
import json
from pathlib import Path

import pymupdf

from eda.ocr import configure_tesseract
from eda.ocr import preprocess_for_ocr
from eda.ocr import render_page_for_ocr
from eda.ocr import run_ocr
from eda.ocr import validate_ocr_languages
from eda.ocr_regions import crop_region
from eda.ocr_regions import detect_text_regions
from eda.ocr_regions import draw_regions
from eda.ocr_regions import merge_overlapping_regions
from eda.ocr_regions import (
    expand_regions_vertically,
)
DEFAULT_PROFILES = (
    "fas+eng",
    "eng+fas",
    "eng",
)


def validate_pdf_path(
    pdf_path: Path,
) -> None:
    if not pdf_path.exists():
        raise SystemExit(
            f"File not found: {pdf_path}"
        )

    if not pdf_path.is_file():
        raise SystemExit(
            f"Path is not a file: {pdf_path}"
        )

    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(
            f"File is not a PDF: {pdf_path}"
        )


def get_required_languages(
    profiles: list[str],
) -> str:
    languages = []

    for profile in profiles:
        for language in profile.split("+"):
            if language not in languages:
                languages.append(language)

    return "+".join(languages)


def result_to_dict(
    result,
) -> dict:
    return {
        "text": result.text,
        "mean_confidence": (
            result.mean_confidence
        ),
        "word_count": result.word_count,
        "low_confidence_words": list(
            result.low_confidence_words
        ),
    }


def make_preview(
    text: str,
    max_characters: int,
) -> str:
    compact = " ".join(
        text.split()
    )

    if len(compact) <= max_characters:
        return compact

    return (
        compact[:max_characters].rstrip()
        + "..."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Detect PDF text regions and "
            "run multiple OCR profiles"
        )
    )

    parser.add_argument(
        "pdf_path",
        help="Path to the PDF file",
    )

    parser.add_argument(
        "--page",
        type=int,
        required=True,
        help="One-based page number",
    )

    parser.add_argument(
        "--layout-psm",
        type=int,
        choices=(3, 6, 11),
        default=3,
        help=(
            "PSM used only for automatic "
            "region detection"
        ),
    )

    parser.add_argument(
        "--region-psm",
        type=int,
        choices=(6, 7, 11),
        default=6,
        help=(
            "PSM used for OCR inside "
            "each detected region"
        ),
    )

    parser.add_argument(
        "--preprocess",
        choices=(
            "original",
            "enhanced",
            "binary",
        ),
        default="enhanced",
    )

    parser.add_argument(
        "--direction",
        choices=("rtl", "ltr"),
        default="rtl",
    )

    parser.add_argument(
        "--profiles",
        nargs="+",
        default=list(DEFAULT_PROFILES),
        help=(
            "OCR language profiles, for example "
            "fas+eng eng+fas eng"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Directory for annotated image, "
            "crops and JSON report"
        ),
    )

    parser.add_argument(
        "--preview-characters",
        type=int,
        default=180,
    )

    parser.add_argument(
        "--crop-vertical-padding",
        type=int,
        default=None,
        help=(
            "Pixels added above and below "
            "each merged OCR region."
        ),
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    validate_pdf_path(pdf_path)

    if args.page < 1:
        raise SystemExit(
            "Page number must be greater than zero."
        )

    configure_tesseract()

    required_languages = (
        get_required_languages(
            args.profiles
        )
    )

    validate_ocr_languages(
        required_languages
    )

    output_dir = (
        args.output_dir
        if args.output_dir
        else Path(
            f"data/debug/"
            f"page-{args.page}-regions"
        )
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    crops_dir = (
        output_dir / "crops"
    )

    crops_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    doc = pymupdf.open(
        str(pdf_path)
    )

    report = {
        "pdf_path": str(pdf_path),
        "page": args.page,
        "layout_psm": args.layout_psm,
        "region_psm": args.region_psm,
        "preprocess": args.preprocess,
        "direction": args.direction,
        "profiles": args.profiles,
        "regions": [],
    }

    try:
        if args.page > len(doc):
            raise SystemExit(
                f"Page {args.page} does not exist. "
                f"PDF has {len(doc)} pages."
            )

        page = doc.load_page(
            args.page - 1
        )

        with render_page_for_ocr(
            page
        ) as original_image:
            with preprocess_for_ocr(
                original_image,
                args.preprocess,
            ) as processed_image:
                detected_regions = detect_text_regions(
                    processed_image,
                    languages="fas+eng",
                    psm=args.layout_psm,
                    direction=args.direction,
                )

                row_step = max(
                    20,
                    processed_image.height // 100,
                )

                regions = merge_overlapping_regions(
                    detected_regions,
                    row_step=row_step,
                    direction=args.direction,
                    min_horizontal_overlap_ratio=0.60,
                )

                vertical_padding = (
                    args.crop_vertical_padding
                )

                if vertical_padding is None:
                    vertical_padding = max(
                        24,
                        round(
                            processed_image.height
                            * 0.025
                        ),
                    )

                ocr_regions = expand_regions_vertically(
                    regions,
                    image_height=processed_image.height,
                    vertical_padding=vertical_padding,
                )

                report["regions_before_merge"] = len(
                    detected_regions
                )

                report["regions_after_merge"] = len(
                    regions
                )

                report["crop_vertical_padding"] = (
                    vertical_padding
                )

                with draw_regions(
                        processed_image,
                        ocr_regions,
                ) as annotated_image:
                    annotated_image.save(
                        output_dir
                        / "annotated.png"
                    )

                for region in ocr_regions:
                    crop_path = (
                        crops_dir
                        / (
                            f"region-"
                            f"{region.region_id:03d}.png"
                        )
                    )

                    with crop_region(
                        processed_image,
                        region,
                    ) as region_image:
                        region_image.save(
                            crop_path
                        )

                        profile_results = {}

                        for profile in args.profiles:
                            result = run_ocr(
                                region_image,
                                languages=profile,
                                psm=args.region_psm,
                            )

                            profile_results[
                                profile
                            ] = result_to_dict(
                                result
                            )

                    report["regions"].append({
                        "region_id": (
                            region.region_id
                        ),
                        "block_number": (
                            region.block_number
                        ),
                        "box": list(region.box),
                        "width": region.width,
                        "height": region.height,
                        "probe_word_count": (
                            region.word_count
                        ),
                        "probe_confidence": (
                            region.probe_confidence
                        ),
                        "probe_text": (
                            region.probe_text
                        ),
                        "crop_path": str(
                            crop_path
                        ),
                        "profiles": (
                            profile_results
                        ),

                    })



    finally:
        doc.close()

    report_path = (
        output_dir / "regions.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"Page: {args.page}"
    )
    print(
        f"Detected regions: "
        f"{len(report['regions'])}"
    )
    print(
        f"Annotated image: "
        f"{output_dir / 'annotated.png'}"
    )
    print(
        f"JSON report: {report_path}"
    )
    print(
        f"Regions before merge: "
        f"{len(detected_regions)}"
    )

    print(
        f"Regions after merge: "
        f"{len(regions)}"
    )

    for region in report["regions"]:
        print()
        print(
            f"Region {region['region_id']}"
        )
        print(
            f"Box: {region['box']}"
        )
        print(
            f"Probe confidence: "
            f"{region['probe_confidence']}"
        )

        for profile, result in (
            region["profiles"].items()
        ):
            confidence = (
                result["mean_confidence"]
            )

            if confidence is None:
                confidence_label = (
                    "not_available"
                )
            else:
                confidence_label = (
                    f"{confidence:.1f}"
                )

            preview = make_preview(
                result["text"],
                args.preview_characters,
            )

            print(
                f"  {profile}: "
                f"words={result['word_count']}, "
                f"confidence={confidence_label}"
            )

            print(
                f"    {preview or '[no text]'}"
            )


if __name__ == "__main__":
    main()