import re

ARTICLE_PATTERN = r"\n\s*ماده\d+"


def split_articles(text: str) -> list[str]:
    positions = [m.start() for m in re.finditer(ARTICLE_PATTERN, text)]
    bounds = positions + [len(text)]

    chunks = []
    for i in range(len(positions)):
        chunks.append(text[bounds[i] : bounds[i + 1]])

    return chunks

def split_fixed(text: str, size: int = 512, overlap: int = 64) -> list[str]:
    words = text.split()
    step = size - overlap

    chunks = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + size])
        if len(chunk) > 50:
            chunks.append(chunk)

    return chunks