import argparse
from pathlib import Path

import pymupdf

from eda.ocr import OCR_LANGUAGES
from eda.ocr import configure_tesseract
from eda.ocr import preprocess_for_ocr
from eda.ocr import render_page_for_ocr
from eda.ocr import run_ocr
from eda.ocr import validate_ocr_languages


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run configurable OCR "
            "on one PDF page"
        )
    )

    parser.add_argument(
        "pdf_path",
        help="Path to the PDF file",
    )

    parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="One-based page number",
    )

    parser.add_argument(
        "--psm",
        type=int,
        choices=(3, 6, 11),
        default=3,
        help="Tesseract page segmentation mode",
    )

    parser.add_argument(
        "--preprocess",
        choices=(
            "original",
            "enhanced",
            "binary",
        ),
        default="original",
        help="Image preprocessing mode",
    )

    parser.add_argument(
        "--save-image",
        type=Path,
        help=(
            "Optional path for saving "
            "the processed image"
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
    validate_ocr_languages(
        OCR_LANGUAGES
    )

    doc = pymupdf.open(str(pdf_path))

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
                if args.save_image:
                    args.save_image.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    processed_image.save(
                        args.save_image
                    )

                result = run_ocr(
                    processed_image,
                    languages=OCR_LANGUAGES,
                    psm=args.psm,
                )

    finally:
        doc.close()

    print(f"Page: {args.page}")
    print(f"PSM: {args.psm}")
    print(
        f"Preprocess: {args.preprocess}"
    )
    print(
        f"Characters: {len(result.text)}"
    )
    print(
        f"Recognized words: "
        f"{result.word_count}"
    )

    if result.mean_confidence is None:
        print("Mean confidence: not_available")
    else:
        print(
            f"Mean confidence: "
            f"{result.mean_confidence:.1f}"
        )

    print(
        f"Low-confidence words: "
        f"{len(result.low_confidence_words)}"
    )

    if result.low_confidence_words:
        preview = ", ".join(
            result.low_confidence_words[:20]
        )

        print(
            f"Low-confidence preview: "
            f"{preview}"
        )

    print("\nOCR text")
    print("-" * 40)

    if result.text:
        print(result.text)
    else:
        print("[No text detected]")


if __name__ == "__main__":
    main()