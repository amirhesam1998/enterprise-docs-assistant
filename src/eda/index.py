import os
import uuid
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def ensure_collection(client, collection):
    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )


def ingest_chunks(chunks, client, collection="docs"):
    if not chunks:
        return 0
    model = get_model()
    ensure_collection(client, collection)
    vecs = model.encode([c.text for c in chunks])
    points = [
        PointStruct(
            id=str(uuid.uuid5(NAMESPACE, c.chunk_id)),
            vector=vec.tolist(),
            payload={
                "text": c.text, "tenant_id": c.tenant_id,
                "source": c.source, "source_type": c.source_type,
                "location": c.location, "acl_groups": c.acl_groups,
                "chunk_id": c.chunk_id,
            },
        )
        for c, vec in zip(chunks, vecs)
    ]
    client.upsert(collection_name=collection, points=points)
    return len(points)