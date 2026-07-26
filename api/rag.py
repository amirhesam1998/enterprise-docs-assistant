from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny
import ollama

from api.config import OLLAMA_MODEL, OLLAMA_URL, QDRANT_COLLECTION, QDRANT_URL

# Qdrant server, not embedded file mode. Constructing this is cheap (no connection
# is opened until the first query), so it can live at module scope.
client = QdrantClient(url=QDRANT_URL)

# Ollama runs on the host, outside Docker, so it needs an explicit base URL —
# the library's implicit default (127.0.0.1) would point at the container itself.
ollama_client = ollama.Client(host=OLLAMA_URL)

# bge-m3 is ~2GB. Loading it per request made every /ask pay the load cost, so it
# is loaded once on first use and reused. Answers are unchanged.
_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("BAAI/bge-m3")
    return _model


def search_and_answer(question, tenant_id, user_groups, k=5):
    model = get_model()
    question_vector = model.encode(question).tolist()
    hits = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=question_vector,
        limit=k,
        query_filter=Filter(must=[
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            FieldCondition(key="acl_groups", match=MatchAny(any=user_groups)),
        ]),
    ).points

    context = "\n\n---\n\n".join(h.payload["text"] for h in hits[:k])
    prompt = f"""بر اساس متن زیر به سوال جواب بده. فقط از همین متن استفاده کن.

    متن:
    {context}

    سوال: {question}
    """

    response = ollama_client.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = response["message"]["content"]

    return {
        "answer": answer,
        "sources": [
            {
                "ref": h.payload["location"].get("ref"),
                "source": h.payload["source"],
                "location": h.payload["location"],
                "score": h.score,
            }
            for h in hits
        ],
    }