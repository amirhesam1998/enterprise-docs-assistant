# from sentence_transformers import SentenceTransformer
# from qdrant_client import QdrantClient
# import ollama
#
# # فقط برای embedِ سوال (یه جمله، آنی)
# model = SentenceTransformer("BAAI/bge-m3")
# client = QdrantClient(path="data/qdrant")
#
# question = "How do I convert a value from one data type to another?"
# q_vec = model.encode(question).tolist()
#
# # جستجو در Qdrant — بدون embed مجدد چانک‌ها
# hits = client.query_points(
#     collection_name="postgres",
#     query=q_vec,
#     limit=5,
# ).points
#
# for h in hits:
#     print(f"\n[{h.score:.3f}] point {h.id}")
#     print(h.payload["text"][:200])
#
# # جواب
# context = "\n\n---\n\n".join(h.payload["text"] for h in hits)
# prompt = f"""Answer based only on the text below.
#
# Text:
# {context}
#
# Question: {question}
# """
#
# response = ollama.chat(
#     model="llama3.1:8b-local",
#     messages=[{"role": "user", "content": prompt}],
# )
# print("\n\n=== جواب ===")
# print(response["message"]["content"])
# client.close()
#
#
#
#


import os

from sentence_transformers import SentenceTransformer , CrossEncoder
from qdrant_client import QdrantClient
import ollama

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")

# فقط برای embedِ سوال (یه جمله، آنی)
model = SentenceTransformer("BAAI/bge-m3")
client = QdrantClient(url=QDRANT_URL)
ollama_client = ollama.Client(host=OLLAMA_URL)
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")

# question = "How do I convert a value from one data type to another?"
# question = "What is the money data type storage size?"
# question = "What is the storage size of the money type?"
# question = "How do enum types handle case sensitivity?"
# question = "What are the two syntaxes for type casting?"
# question = "How does an autoincrementing column work?"
# question = "Can I store salary figures with cents in Postgres?"
# question = "What does lc_monetary control?"
# question = "How do serial and bigserial differ in size?"
# question = "Why shouldn't I use floats for financial data?"
# question = "How can I make a column fill itself automatically?"
# question = "What happens to the sequence if I delete a column?"
question = "Is there a gap-free auto-increment in Postgres?"
q_vec = model.encode(question).tolist()

# جستجو در Qdrant — بدون embed مجدد چانک‌ها
hits = client.query_points(
    collection_name="postgres",
    query=q_vec,
    limit=20,
).points

# for h in hits:
#     print(f"\n[{h.score:.3f}] point {h.id}")
#     print(h.payload["text"][:200])

pairs = [[question, h.payload["text"]] for h in hits]
scores = reranker.predict(pairs)
ranked = sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)
top_hits = [h for _, h in ranked[:5]]
print("=== بعد از rerank ===")
for score, h in ranked[:5]:
    print(f"[{score:.3f}] point {h.id}")
    print(h.payload["text"][:150])

# جواب
context = "\n\n---\n\n".join(h.payload["text"] for h in top_hits)
prompt = f"""Answer based only on the text below.

Text:
{context}

Question: {question}
"""

response = ollama_client.chat(
    model=os.getenv("OLLAMA_MODEL", "llama3.1:8b-local"),
    messages=[{"role": "user", "content": prompt}],
)
print("\n\n=== جواب ===")
print(response["message"]["content"])
client.close()




