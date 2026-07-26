from pathlib import Path
import pymupdf
from eda.normalize import normalize_chars , normalize_space
from eda.chunk import split_articles
DATA_DIR = Path("data/raw/asnad")

FA_START, FA_END = "\u0600", "\u06FF"
EMPTY_PAGE_THRESHOLD = 50


def persian_ratio(text: str) -> float:
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    fa = sum(1 for ch in chars if FA_START <= ch <= FA_END)
    return fa / len(chars)


def analyze_pdf(path: Path) -> dict:
    doc = pymupdf.open(path)

    text_lens = []
    table_pages = 0
    image_count = 0
    fa_ratios = []

    for page in doc:
        text = page.get_text()
        text = normalize_chars(text)
        text = normalize_space(text)
        text = split_articles(text)
        text_lens.append(len(text))

        try:
            if len(page.find_tables().tables) > 0:
                table_pages += 1
        except Exception:
            pass  # find_tables روی بعضی صفحه‌های گرافیکی می‌ترکه

        image_count += len(page.get_images(full=True))
        fa_ratios.append(persian_ratio(text))

    doc.close()

    pages = len(text_lens)
    if pages == 0:
        return {"file": path.name, "pages": 0}

    return {
        "file": path.name,
        "pages": pages,
        "avg_chars": round(sum(text_lens) / pages),
        "empty_pages": sum(1 for n in text_lens if n < EMPTY_PAGE_THRESHOLD),
        "table_page_pct": round(100 * table_pages / pages),
        "images": image_count,
        "fa_pct": round(100 * sum(fa_ratios) / pages),
    }


def main():
    rows = []
    for pdf in sorted(DATA_DIR.glob("*.pdf")):
        print(f"... {pdf.name}", flush=True)
        rows.append(analyze_pdf(pdf))

    print(f"\n{'file':<45} {'pg':>4} {'avg_ch':>7} {'empty':>6} {'tbl%':>5} {'img':>5} {'fa%':>4}")
    print("-" * 82)
    for r in rows:
        print(
            f"{r['file']:<45} {r['pages']:>4} {r.get('avg_chars', 0):>7} "
            f"{r.get('empty_pages', 0):>6} {r.get('table_page_pct', 0):>5} "
            f"{r.get('images', 0):>5} {r.get('fa_pct', 0):>4}"
        )


if __name__ == "__main__":
    main()