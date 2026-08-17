import pymupdf
from PIL import Image


MIN_TEXT_CHARS = 50

RENDER_DPI = 72
WHITE_THRESHOLD = 245
MIN_VISUAL_COVERAGE = 0.01


def get_displayed_image_metrics(
    page: pymupdf.Page,
) -> tuple[int, float]:
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    if page_area <= 0:
        return 0, 0.0

    displayed_image_count = 0
    largest_image_coverage = 0.0

    image_infos = page.get_image_info(xrefs=False)

    for image_info in image_infos:
        image_rect = pymupdf.Rect(
            image_info["bbox"]
        )

        visible_rect = image_rect & page_rect

        visible_width = max(
            0.0,
            visible_rect.width,
        )
        visible_height = max(
            0.0,
            visible_rect.height,
        )
        visible_area = (
            visible_width * visible_height
        )

        if visible_area <= 0:
            continue

        displayed_image_count += 1

        coverage = min(
            visible_area / page_area,
            1.0,
        )

        if coverage > largest_image_coverage:
            largest_image_coverage = coverage

    return (
        displayed_image_count,
        largest_image_coverage,
    )


def calculate_visual_coverage(
    page: pymupdf.Page,
) -> float:
    # صفحه با رزولوشن پایین و به‌صورت خاکستری
    # رندر می‌شود.
    pixmap = page.get_pixmap(
        dpi=RENDER_DPI,
        colorspace=pymupdf.csGRAY,
        alpha=False,
    )

    total_pixels = pixmap.width * pixmap.height

    if total_pixels <= 0:
        return 0.0

    # تبدیل Pixmap به تصویر Pillow
    with Image.frombytes(
        "L",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    ) as image:
        histogram = image.histogram()

    # پیکسل‌های تیره‌تر از WHITE_THRESHOLD
    # به‌عنوان محتوای قابل‌مشاهده محسوب می‌شوند.
    non_white_pixels = sum(
        histogram[:WHITE_THRESHOLD]
    )

    return non_white_pixels / total_pixels


def inspect_pdf(path: str) -> list[dict]:
    results = []

    doc = pymupdf.open(path)

    try:
        for page_index, page in enumerate(doc):
            # TODO 1: استخراج متن قابل‌استخراج
            text = page.get_text("text").strip()
            char_count = len(text)

            # TODO 2: اطلاعات خام تصاویر برای Debug
            raw_image_count = len(
                page.get_images(full=True)
            )

            (
                displayed_image_count,
                largest_image_coverage,
            ) = get_displayed_image_metrics(page)

            # TODO 3: تشخیص نوع صفحه
            visual_coverage = None

            if char_count >= MIN_TEXT_CHARS:
                page_type = "text"

            else:
                visual_coverage = (
                    calculate_visual_coverage(page)
                )

                if (
                    visual_coverage
                    >= MIN_VISUAL_COVERAGE
                ):
                    page_type = "scanned_candidate"
                else:
                    page_type = "empty_or_unknown"

            # TODO 4: ذخیره نتیجه
            results.append({
                "page_index": page_index,
                "page_number": page_index + 1,
                "char_count": char_count,
                "raw_image_count": raw_image_count,
                "displayed_image_count": (
                    displayed_image_count
                ),
                "largest_image_coverage": (
                    largest_image_coverage
                ),
                "visual_coverage": visual_coverage,
                "page_type": page_type,
            })

        return results

    finally:
        doc.close()