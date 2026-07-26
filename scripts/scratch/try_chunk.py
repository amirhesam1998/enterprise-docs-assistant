import pymupdf
from eda.normalize import normalize_chars, normalize_space
from eda.chunk import split_articles

doc = pymupdf.open("data/raw/asnad/ghanon-kar.pdf")
text = normalize_chars("".join(p.get_text() for p in doc))
doc.close()

chunks = [normalize_space(c) for c in split_articles(text)]

print(f"تعداد چانک: {len(chunks)}")
print(f"کوتاه‌ترین: {min(len(c) for c in chunks)}")
print(f"بلندترین:  {max(len(c) for c in chunks)}")
print("\n--- چانک ۰ ---")
print(chunks[0])
print("\n--- چانک ۵۰ ---")
print(chunks[50])