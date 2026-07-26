import os

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

model = SentenceTransformer("BAAI/bge-m3")
client = QdrantClient(url=QDRANT_URL)


def search(question, tenant_id, user_groups, k=5):
    q_vec = model.encode(question).tolist()
    hits = client.query_points(
        collection_name="docs",
        query=q_vec,
        limit=20,
        query_filter=Filter(must=[
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            FieldCondition(key="acl_groups", match=MatchAny(any=user_groups)),
        ]),
    ).points
    return hits[:k]


if __name__ == "__main__":
    q = "چطور مشکل صورتحساب را حل کنم؟"

    for groups in (["support"], ["billing"], ["security"], ["platform"]):
        hits = search(q, "kb", groups)
        refs = [h.payload["location"].get("ref") for h in hits]
        print(f"{str(groups):15s} → {refs}")