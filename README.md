# Enterprise Docs Assistant

A multi-tenant RAG system with access-control-aware retrieval. It answers natural-language
questions with citations back to the source document and location, while guaranteeing that no
tenant ever sees another tenant's data and no user retrieves documents outside their permission
groups.

The defining property: **two users asking the identical question receive different answers from
different documents**, because access control is enforced inside the vector search rather than
around it.

---

## Why this exists

Most RAG demos index one clean corpus and stop. Real enterprise deployments need two things that
reference implementations almost never have, and both are treated here as the primary engineering
problem — validated by test, not asserted:

1. **Multi-tenancy** — several organizations share one system; their data must never cross.
2. **ACL-aware retrieval** — access filtering happens *inside* the vector search. Post-filtering
   (retrieve, then drop disallowed results) silently truncates the result set and the model
   answers from whatever survives.

---

## Features

- **Multi-tenant isolation** with an adversarial leak-test suite and a negative control.
- **Group-level ACL** enforced as a pre-filter inside Qdrant.
- **Two orthogonal authorization systems**: ACL (which documents) and dynamic RBAC (which
  features), kept strictly separate.
- **Multi-format ingestion** through a parser registry — PDF, XLSX, DOCX, and images (OCR) — where
  adding a format is one parser plus one line.
- **Async document upload** via Celery, with identity stamped from the uploader's token.
- **Hybrid retrieval** (dense + BM25) with cross-encoder reranking.
- **Evaluation harness** with stable, chunk-id-based ground truth.
- **JWT auth** with a React frontend and one-command Docker startup.

---

## Architecture

```
Ingestion:  PDF / XLSX / DOCX / image
                    |  parser registry (parse_any)
                    v
              Chunk  (intermediate representation)
                    |  embed (BAAI/bge-m3, 1024-dim)
                    v
              Qdrant - single collection, payload carries tenant_id + acl_groups

Query:      question + identity (from JWT)
                    |  vector search with MANDATORY pre-filter:
                    |  tenant_id == X  AND  acl_groups intersect user_groups
                    v
              cross-encoder rerank -> LLM generation -> answer + citations

Upload:     file -> /documents/upload -> Celery task (worker) -> parse -> embed -> index
```

The `Chunk` dataclass is the architectural centerpiece. Every parser converts its format into it;
nothing downstream knows or cares whether the source was a PDF, a spreadsheet, a Word file, or a
scanned image. `location` is polymorphic — `{type: page, num}` for PDF, `{type: cell, sheet, row}`
for spreadsheets, `{type: paragraph, index}` for Word, `{type: image, num}` for images — so each
format cites itself in its own terms without null columns.

---

## Tech stack

Python 3.12 · uv · FastAPI · Celery + Redis · Qdrant · sentence-transformers (bge-m3,
bge-reranker-v2-m3) · Ollama (LLM, on host) · Tesseract (OCR) · SQLite + SQLAlchemy · React +
Vite + TypeScript + Tailwind · Docker Compose.

---

## Getting started

### Prerequisites

- Docker and Docker Compose
- [Ollama](https://ollama.com) running on the host with a local model available
  (the app expects `llama3.1:8b-local`). Ollama stays outside Docker deliberately — the LLM is
  swappable and its image is heavy.
- For image OCR: Tesseract is installed inside the API/worker image automatically; no host
  install needed when running via Docker.

### Run

```bash
# 1. Start Ollama on the host, bound so containers can reach it
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# 2. Bring up the stack (Qdrant, API, frontend, Redis, Celery worker)
docker compose up -d

# 3. First-time only: index the sample tenants
docker compose run --rm api python scripts/build_index.py
```

Then open:
- Frontend: http://localhost:5173
- API docs: http://localhost:8000/docs
- Qdrant:   http://localhost:6333

### Demo accounts

All passwords are `<username>123`.

| user   | level   | tenant          | groups        |
|--------|---------|-----------------|---------------|
| sara   | admin   | kb              | billing       |
| reza   | admin   | kb              | security      |
| ali    | user    | postgres        | engineering   |
| maryam | user    | postgres        | hr            |
| dana   | user    | acme-internal   | sales         |

`sara` and `reza` are the key pair — same tenant, different groups. Ask both the same billing
question and watch the sources diverge.

---

## Isolation, proven

Filtering is a hard constraint on the query, executed inside the vector engine:

```python
Filter(must=[
    FieldCondition(key="tenant_id",  match=MatchValue(value=tenant_id)),
    FieldCondition(key="acl_groups", match=MatchAny(any=user_groups)),
])
```

Because it runs inside the search rather than around it, no prompt content can influence it —
prompt injection has no surface to attack.

**Adversarial leak suite** — 20 queries across tenants, including exfiltration attempts and prompt
injection:

| Configuration                     | Cross-tenant leaks |
|-----------------------------------|--------------------|
| Pre-filtering enabled             | **0 / 20**         |
| Pre-filtering disabled (control)  | **20 / 20**        |

The control row is the point: a passing test proves nothing unless it can also fail. Running the
control also exposed a bug in the test itself — a tenant was named `acme` while the index used
`acme-internal`, so half the queries had silently been testing a nonexistent tenant.

---

## Retrieval quality

Evaluated with chunk-id-based ground truth (stable across re-indexing, unlike integer point IDs):

| Configuration                      | recall@1 | recall@5 |
|------------------------------------|----------|----------|
| embedding + rerank                 | 0.75     | 0.92     |
| hybrid (BM25 + embedding) + rerank | 0.83     | 0.92     |

On this keyword-heavy set, hybrid improved recall@1 — the gain concentrated on exact-term queries
(e.g. "dollar signs" -> the dollar-quoting section) where BM25's lexical match rescues a result
dense retrieval ranks lower. On an earlier, cleaner corpus hybrid showed **no** gain; reporting
both is the honest result. Knowing when a technique doesn't earn its complexity is as useful as
knowing when it does.

---

## Two authorization systems

Kept deliberately separate — conflating them breaks both:

| System | Controls | Mechanism |
|--------|----------|-----------|
| **ACL**  | which documents a user retrieves | `tenant_id` + `acl_groups`, pre-filtered in Qdrant |
| **RBAC** | which features a user can invoke | `level` (creator/admin/user) + dynamic roles/permissions |

A user can be an admin (RBAC) who only reads billing documents (ACL). Identity for both always
comes from the JWT, never the request body — accepting it from the body would be a
privilege-escalation hole.

---

## Multi-format ingestion

A parser registry maps extension to parser:

```python
PARSERS = {".pdf": parse_pdf, ".xlsx": parse_xlsx, ".docx": parse_docx,
           ".png": parse_image, ".jpg": parse_image, ".jpeg": parse_image}
```

Adding a format is one parser plus one line — proven with Word, which uploaded through the UI
without touching the queue, endpoint, or frontend. Uploaded documents are stamped with the
uploader's tenant and groups, and their chunk IDs are namespaced by tenant so two tenants
uploading a same-named file never collide.

**OCR note:** English extraction is strong; Persian OCR is a basic baseline. Rather than sink time
into Persian OCR tuning for a low-frequency format, a working baseline ships and quality
improvement is left as future work.

---

## Project layout

```
src/eda/        pipeline library (framework-agnostic - no FastAPI imports)
  schema.py     Chunk - the intermediate representation
  parse.py      parsers + parse_any registry
  normalize.py  Unicode normalization + persian_ratio
  chunk.py      chunking strategies
  index.py      ingest_chunks(), lazy model singleton, uuid5 point IDs
api/            FastAPI service - auth, RAG, admin, documents, Celery tasks
scripts/        build_index.py, search.py, eval.py, leak_test.py
frontend/       React app
data/           (gitignored) Qdrant storage, SQLite DB, uploads, source files
```

---

## Notes on Persian text

The corpus surfaced findings that would have silently corrupted retrieval:

- **Two Unicode families** — standard Arabic block vs. deprecated Presentation Forms. Visually
  identical, byte-wise unrelated; NFKC + character folding collapses them. A ratio metric computed
  *before* normalization nearly discarded a third of the corpus as non-Persian.
- **Unrecoverable ligature reordering** — the lam-alef ligature extracts transposed and can't be
  repaired at the source; the fix applies the same transformation to queries, preserving lexical
  match by symmetry.
- **Language is per-chunk, not per-tenant** — a single file mixes Persian and English, so detection
  runs on each chunk.

---

## Known limitations / roadmap

- `SECRET_KEY` should come from the environment in all deployments.
- Permissions are baked into the JWT — a revoked permission stays live until token expiry (60m).
- Persian OCR quality is basic.
- Word chunking is fixed-size; structural (heading-based) chunking would keep language and section
  boundaries clean.

---

## License

See `LICENSE`.
