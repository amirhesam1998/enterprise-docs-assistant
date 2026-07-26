import pymupdf
from eda.chunk import split_fixed
from eda.schema import Chunk
import openpyxl
from eda.normalize import persian_ratio
import os
import docx
import pytesseract
from PIL import Image

# Tesseract is a system binary, not a Python package, so its location is a
# property of the machine rather than of this repo. Default to whatever
# `tesseract` is on PATH — correct inside the container, where the image installs
# it — and let TESSERACT_CMD override on hosts that keep it somewhere else
# (a Windows dev box, typically). Nothing machine-specific is hardcoded here.
_TESSERACT_CMD = os.getenv("TESSERACT_CMD")
if _TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD



def parse_pdf(path, tenant_id, source, acl_groups=None, lang="en",
              page_start=0, page_end=None):
    if acl_groups is None:
        acl_groups = []

    doc = pymupdf.open(path)
    if page_end is None:
        page_end = len(doc)

    chunks = []
    for page_num, page in enumerate(doc):
        if page_num < page_start:
            continue
        if page_num >= page_end:
            break
        text = page.get_text()
        for i, piece in enumerate(split_fixed(text)):
            chunks.append(Chunk(
                text=piece,
                lang=lang,
                tenant_id=tenant_id,
                source=source,
                source_type="pdf",
                location={"type": "page", "num": page_num},
                acl_groups=acl_groups,
                chunk_id=f"{source}-{page_num}_{i}",
            ))

    doc.close()
    return chunks

def parse_xlsx(path, tenant_id, source, acl_groups=None):
    if acl_groups is None:
        acl_groups = []
    wb = openpyxl.load_workbook(path, data_only=True)
    chunks = []

    for sheet_name in wb.sheetnames:
        if sheet_name.startswith("_"):
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))

        # هدر: اولین ردیف با ۷۰٪ پر
        header_row = None
        for r, row in enumerate(rows):
            filled = sum(1 for v in row if v is not None and str(v).strip())
            if filled >= len(row) * 0.7:
                header_row = r
                break
        if header_row is None:
            continue
        headers = rows[header_row]
        data_rows = rows[header_row + 1:]

        text_col_idx = []
        for col in range(len(headers)):
            lengths = [len(str(row[col])) for row in data_rows
                       if col < len(row) and row[col] is not None]
            if lengths and sum(lengths) / len(lengths) > 40:  # میانگین > ۴۰ کاراکتر
                text_col_idx.append(col)


        # TODO: برای هر ردیف داده، متن رو از ستون‌های متنی بساز
        for r, row in enumerate(data_rows):
            filled = sum(1 for v in row if v is not None and str(v).strip())
            if filled < 2:  # جداکننده رو رد کن
                continue
            parts = []
            for col in text_col_idx:
                if col < len(row) and row[col] is not None and str(row[col]).strip():
                    parts.append(f"{headers[col]}: {row[col]}")
            text = "\n".join(parts)
            if not text:
                continue
            chunks.append(Chunk(
                text=text,
                lang="fa" if persian_ratio(text) > 0.5 else "en",
                tenant_id=tenant_id,
                source=source,
                source_type="xlsx",
                location={
                    "type": "cell",
                    "sheet": sheet_name,
                    "row": header_row + 1 + r + 1,
                    "ref": str(row[0]) if row[0] else None,
                },
                acl_groups=acl_groups,  # ← از پارامتر، نه فایل
                chunk_id=f"{source}-{sheet_name}-{r}",
            ))

        # TODO: Chunk بساز — acl_groups از پارامتر، نه از فایل

    return chunks


def parse_docx(path, tenant_id, source, acl_groups=None, lang="en"):
    if acl_groups is None:
        acl_groups = []
    doc = docx.Document(path)
    full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    chunks = []
    for i, piece in enumerate(split_fixed(full_text)):
        chunks.append(Chunk(
            text=piece,
            lang="fa" if persian_ratio(piece) > 0.5 else "en",   # ← خودکار
            tenant_id=tenant_id,
            source=source,
            source_type="docx",
            location={"type": "paragraph", "index": i},
            acl_groups=acl_groups,
            chunk_id=f"{source}-{i}",
        ))
    return chunks


def parse_image(path, tenant_id, source, acl_groups=None):
    if acl_groups is None:
        acl_groups = []

    # OCR — هر دو زبان، بذار خودش تشخیص بده
    img = Image.open(path)
    text = pytesseract.image_to_string(img, lang="eng+fas")
    text = text.strip()

    if not text:
        return []      # عکس بدون متن (یا OCR شکست خورد)

    chunks = []
    for i, piece in enumerate(split_fixed(text)):
        chunks.append(Chunk(
            text=piece,
            lang="fa" if persian_ratio(piece) > 0.5 else "en",
            tenant_id=tenant_id,
            source=source,
            source_type="image",
            location={"type": "image", "num": i},
            acl_groups=acl_groups,
            chunk_id=f"{source}-{i}",
        ))
    return chunks


PARSERS = {
    ".pdf": parse_pdf,
    ".xlsx": parse_xlsx,
    ".docx": parse_docx,
    ".png": parse_image,      # ← سه خط برای سه فرمت تصویر
    ".jpg": parse_image,
    ".jpeg": parse_image,
}


def parse_any(path, tenant_id, source, acl_groups=None, **kwargs):
    ext = os.path.splitext(path)[1].lower()
    parser = PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"فرمت پشتیبانی نمی‌شود: {ext}")
    return parser(path, tenant_id, source, acl_groups=acl_groups, **kwargs)