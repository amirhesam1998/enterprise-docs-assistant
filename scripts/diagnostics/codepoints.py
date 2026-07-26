from collections import Counter
from pathlib import Path
import sys
import pymupdf
from eda.normalize import normalize_chars , normalize_space

SAMPLE_PAGES = 10

def codepoint_ranges(text: str) -> Counter:
    c = Counter()
    for ch in text:
        cp = ord(ch)
        if 0x0600 <= cp <= 0x06FF:   c["arabic_standard"] += 1
        elif 0xFB50 <= cp <= 0xFEFF: c["presentation_forms"] += 1
        elif 0xE000 <= cp <= 0xF8FF: c["private_use"] += 1
        elif ch.isascii():           c["ascii"] += 1
        elif ch.isspace():           c["space"] += 1
        else:                        c[f"other_{hex(cp)}"] += 1
    return c

def main():
    path = Path(sys.argv[1])
    doc = pymupdf.open(path)

    start = max(0 , len(doc) // 2 - SAMPLE_PAGES // 2)
    pages = range(start, min(start + SAMPLE_PAGES, len(doc)))

    text = "".join(doc[i].get_text() for i in pages)
    text = normalize_chars(text)
    text = normalize_space(text)
    doc.close()

    counts = codepoint_ranges(text)
    total = sum(counts.values())

    print(f"\n{path.name}  (صفحات {start}–{start + len(list(pages)) - 1}، {total} کاراکتر)")
    print("-" * 50)
    for name, n in counts.most_common():
        print(f"  {name:<22} {n:>7} {100 * n / total:>6.1f}%")


if __name__ == "__main__":
    main()