import unicodedata
import re


def normalize_chars(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("ي", "ی")
    text = text.replace("ك", "ک")
    text = text.replace("لا", "ال")
    text = text.replace("\u200c", " ")
    return text


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def persian_ratio(text: str) -> float:
    """چند درصد کاراکترهای غیرفاصله در بازه‌ی یونیکد عربی/فارسی هستند؟"""
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    fa = sum(1 for ch in chars if "\u0600" <= ch <= "\u06FF")
    return fa / len(chars)