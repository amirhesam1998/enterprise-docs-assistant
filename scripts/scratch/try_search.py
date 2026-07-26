import pymupdf
from sentence_transformers import SentenceTransformer
from eda.chunk import split_fixed
import ollama

doc = pymupdf.open("data/raw/postgres/postgresql-17-A4.pdf")
text = "".join(p.get_text() for p in doc[31:231])
doc.close()

chunks = split_fixed(text)
print(f"{len(chunks)} چانک، در حال embedding...")

model = SentenceTransformer("BAAI/bge-m3")
chunk_vecs = model.encode(chunks, show_progress_bar=True)

question = "How do I convert a value from one data type to another?"
q_vec = model.encode([question])

similarities = model.similarity(q_vec, chunk_vecs)
scores = similarities[0]
top = scores.topk(5)

for score, idx in zip(top.values, top.indices):
    print(f"\n[{score:.3f}] چانک {idx}")
    print(chunks[idx][:300])

context = "\n\n---\n\n".join(chunks[idx] for idx in top.indices)
prompt = f"""Answer the question based only on the text below.


Text:
{context}

Question: {question}
"""

response = ollama.chat(
    model="llama3.1:8b-local",
    messages=[{"role": "user", "content": prompt}],
)

print("\n\n=== جواب ===")
print(response["message"]["content"])