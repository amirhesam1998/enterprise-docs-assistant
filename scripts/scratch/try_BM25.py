import os

from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

client = QdrantClient(url=QDRANT_URL)

# همه‌ی point ها رو بگیر
records = client.scroll(collection_name="postgres", limit=1000, with_payload=True)[0]

texts = [r.payload["text"] for r in records]
ids = [r.id for r in records]

# BM25 روی کلمات
bm25 = BM25Okapi([t.split() for t in texts])

# تست: یه سوال بزن
query = "money format currency".split()
scores = bm25.get_scores(query)
print(scores[:10])
print("بیشترین:", max(scores), "در ایندکس", scores.argmax() if hasattr(scores, 'argmax') else scores.index(max(scores)))