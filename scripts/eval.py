from sentence_transformers import SentenceTransformer, CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from rank_bm25 import BM25Okapi
import os

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "docs"
TENANT = "postgres"

model = SentenceTransformer("BAAI/bge-m3")
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
client = QdrantClient(url=QDRANT_URL)

# --- فقط چانک‌های این tenant را برای BM25 بخوان ---
records = client.scroll(
    collection_name=COLLECTION,
    scroll_filter=Filter(must=[
        FieldCondition(key="tenant_id", match=MatchValue(value=TENANT))
    ]),
    limit=1000,
    with_payload=True,
)[0]

texts = [r.payload["text"] for r in records]
chunk_ids = [r.payload["chunk_id"] for r in records]
bm25 = BM25Okapi([t.split() for t in texts])
id_to_text = dict(zip(chunk_ids, texts))

# ground truth بر اساس chunk_id — پایدار در برابر re-index
eval_set = [
    {"q": "How do I write a string without escaping quotes, using dollar signs?",
     "gt": ["postgres.pdf-73_0"]},
    {"q": "How do I reference the first argument in a function body?",
     "gt": ["postgres.pdf-79_0"]},
    {"q": "How can I convert a value to another type using function-like syntax?",
     "gt": ["postgres.pdf-77_0", "postgres.pdf-87_1"]},
    {"q": "What are the two syntaxes for casting a value's type?",
     "gt": ["postgres.pdf-77_0"]},
    {"q": "How do I include special characters in an identifier name?",
     "gt": ["postgres.pdf-71_0"]},
    {"q": "How are comments written in SQL?",
     "gt": ["postgres.pdf-81_0"]},
    {"q": "What is the precedence order of operators?",
     "gt": ["postgres.pdf-82_0", "postgres.pdf-83_0"]},
    {"q": "How does a window function work over partitions?",
     "gt": ["postgres.pdf-85_0", "postgres.pdf-86_0"]},
    {"q": "How do I build a composite value from several fields?",
     "gt": ["postgres.pdf-91_0", "postgres.pdf-92_0"]},
    {"q": "How do I access a single element of an array?",
     "gt": ["postgres.pdf-90_0"]},
    {"q": "Can I use a subquery that returns one value inside an expression?",
     "gt": ["postgres.pdf-84_0"]},
    {"q": "How do aggregate expressions like sum or count work?",
     "gt": ["postgres.pdf-84_0"]},
]


def normalize(scores):
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [0.5] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def _tenant_filter():
    return Filter(must=[
        FieldCondition(key="tenant_id", match=MatchValue(value=TENANT))
    ])


def retrieve(question, k=5):
    """embedding + rerank"""
    q_vec = model.encode(question).tolist()
    hits = client.query_points(
        collection_name=COLLECTION,
        query=q_vec,
        limit=20,
        query_filter=_tenant_filter(),
    ).points
    pairs = [[question, h.payload["text"]] for h in hits]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, hits), key=lambda x: x[0], reverse=True)
    return [h.payload["chunk_id"] for _, h in ranked[:k]]


def retrieve_hybrid(question, alpha=0.5, k=5):
    """embedding + BM25 + rerank"""
    q_vec = model.encode(question).tolist()
    hits = client.query_points(
        collection_name=COLLECTION,
        query=q_vec,
        limit=len(texts),
        query_filter=_tenant_filter(),
    ).points
    emb = {h.payload["chunk_id"]: h.score for h in hits}

    bm_scores = bm25.get_scores(question.split())
    bm = {chunk_ids[i]: bm_scores[i] for i in range(len(chunk_ids))}

    all_ids = list(emb.keys())
    emb_norm = dict(zip(all_ids, normalize([emb[i] for i in all_ids])))
    bm_norm = dict(zip(all_ids, normalize([bm.get(i, 0.0) for i in all_ids])))

    combined = {i: alpha * emb_norm[i] + (1 - alpha) * bm_norm[i] for i in all_ids}
    top20 = sorted(combined, key=combined.get, reverse=True)[:20]

    pairs = [[question, id_to_text[i]] for i in top20]
    rerank_scores = reranker.predict(pairs)
    ranked = sorted(zip(rerank_scores, top20), key=lambda x: x[0], reverse=True)
    return [i for _, i in ranked[:k]]


def run_eval(fn, name):
    hit1 = hit5 = 0
    print(f"\n===== {name} =====")
    for item in eval_set:
        top = fn(item["q"], k=5)
        at1 = top[0] in item["gt"]
        at5 = any(g in top for g in item["gt"])
        hit1 += at1
        hit5 += at5
        mark = "✅" if at5 else "❌"
        rank1 = "🥇" if at1 else "  "
        print(f"{mark}{rank1} {item['q'][:50]}")
        print(f"     گرفت: {top}")
    n = len(eval_set)
    print(f"\nrecall@1 = {hit1/n:.2f}   recall@5 = {hit5/n:.2f}")


run_eval(retrieve, "embedding + rerank")
run_eval(retrieve_hybrid, "hybrid (embedding + BM25) + rerank")