import argparse
from collections import Counter
from pathlib import Path

from parse_config.pdf.pdf_inspector import inspect_pdf


def main() -> None:
    # TODO 1: دریافت مسیر PDF از ترمینال
    parser = argparse.ArgumentParser(
        description="Inspect PDF pages before parsing"
    )

    parser.add_argument(
        "pdf_path",
        help="Path to the PDF file",
    )

    args = parser.parse_args()

    # TODO 2: بررسی مسیر و فرمت فایل
    pdf_path = Path(args.pdf_path)

    if not pdf_path.exists():
        raise SystemExit(f"File not found: {pdf_path}")

    if not pdf_path.is_file():
        raise SystemExit(f"Path is not a file: {pdf_path}")

    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(f"File is not a PDF: {pdf_path}")

    # TODO 3: اجرای Inspector
    results = inspect_pdf(str(pdf_path))

    if not results:
        print("No pages found.")
        return

    # TODO 4: نمایش نتیجه هر صفحه
    for result in results:
        visual_coverage = result["visual_coverage"]

        if visual_coverage is None:
            visual_label = "not_checked"
        else:
            visual_label = f"{visual_coverage:.1%}"

        print(
            f"Page {result['page_number']}: "
            f"type={result['page_type']}, "
            f"chars={result['char_count']}, "
            f"raw_images={result['raw_image_count']}, "
            f"displayed_images="
            f"{result['displayed_image_count']}, "
            f"largest_image="
            f"{result['largest_image_coverage']:.1%}, "
            f"visual_content={visual_label}"
        )

    # TODO 5: محاسبه آمار صفحات
    summary = Counter(
        result["page_type"]
        for result in results
    )

    # TODO 6: نمایش خلاصه
    print("\nSummary")
    print(f"Total pages: {len(results)}")
    print(f"Text pages: {summary['text']}")
    print(
        f"Scanned candidates: "
        f"{summary['scanned_candidate']}"
    )
    print(
        f"Empty or unknown: "
        f"{summary['empty_or_unknown']}"
    )


if __name__ == "__main__":
    main()