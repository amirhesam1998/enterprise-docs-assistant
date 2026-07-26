import pymupdf
from eda.chunk import split_fixed

doc = pymupdf.open("data/raw/postgres/postgresql-17-A4.pdf")
text = "".join(p.get_text() for p in doc[31:231])
doc.close()

chunks = split_fixed(text)
print(f"چانک: {len(chunks)}")
print(chunks[10][:400])
print("---")
print(chunks[50][:400])