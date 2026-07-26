# CLAUDE.md — Enterprise Docs Assistant

## Context Navigation

This project has a graphify knowledge graph at `graphify-out/`.

When you need to understand the code:
1. ALWAYS query the knowledge graph first instead of reading raw files:
   `graphify query "your question"`
2. Only read raw source files if I explicitly say "read the file" or "look at the raw file".
3. After modifying code, run `graphify update .` to keep the graph current.

---

## What this project is

A multi-tenant RAG system with access-control-aware retrieval. Users ask natural-language
questions and get answers with citations, while two guarantees hold: no tenant sees another
tenant's documents, and no user sees documents outside their permission groups.

The defining property — and the thing most changes must not break — is that **two users asking
the identical question get different answers from different documents**, because access control
is enforced inside the vector search, not around it.

---

## Architecture at a glance

```
Ingestion:  PDF / XLSX  →  parser  →  Chunk (intermediate form)  →  embed  →  Qdrant
Query:      question + identity (from JWT)  →  filtered vector search  →  rerank  →  LLM  →  answer
Upload:     file  →  /documents/upload  →  Celery task (worker)  →  parse → embed → index
```

Stack: Python 3.12 · uv · FastAPI · Celery + Redis · Qdrant (server) · Ollama (host, outside
Docker) · sentence-transformers (bge-m3, bge-reranker-v2-m3) · React + Vite + TS · SQLite.

Layout:
```
src/eda/        pipeline library (framework-agnostic, no FastAPI imports)
  schema.py     Chunk dataclass — the intermediate representation everything converts to
  parse.py      parse_pdf, parse_xlsx → list[Chunk]
  normalize.py  Unicode normalization + persian_ratio
  chunk.py      chunking strategies
  index.py      ingest_chunks(), get_model() lazy singleton, uuid5 point IDs
api/            FastAPI service
  main.py       app wiring, CORS, router registration
  auth.py       JWT, CurrentUser, current_user, require_permission guards
  rag.py        search_and_answer() — the ACL/tenant pre-filter lives here
  celery_app.py, tasks.py         async ingestion
  routers/      auth.py, admin.py, documents.py
  models.py, db.py, schemas.py, security.py, seed.py
scripts/        build_index.py, search.py, eval.py, leak_test.py, diagnostics/
frontend/       React app
data/            (gitignored) qdrant/, app.db, uploads/, raw source files
```

---

## Load-bearing conventions — do not break these

**Two orthogonal authorization systems. Never conflate them.**
- ACL (tenant_id + acl_groups) controls WHICH DOCUMENTS a user retrieves. Enforced as a
  pre-filter inside the Qdrant query in `rag.py`. This is the security boundary.
- RBAC (level + roles + permissions) controls WHICH FEATURES a user can invoke. Governs API
  endpoints and UI, never document access.
- A user can be an admin (RBAC) who only reads billing docs (ACL). These axes are independent.

**Identity comes from the JWT, never the request body.** `tenant_id` and groups for `/ask` and
`/documents/upload` are read from the authenticated user. Accepting them from the body is a
privilege-escalation hole. Same rule everywhere.

**Filtering is a pre-filter, never a post-filter.** The tenant/ACL constraint goes inside
`client.query_points(query_filter=...)`. Retrieving then dropping disallowed results silently
truncates the result set. Do not "optimize" it into a post-filter.

**Point IDs are `uuid5(NAMESPACE, chunk_id)`, not integer offsets.** This makes re-ingesting the
same document idempotent (overwrite, not duplicate) and removes the old manual `id_offset`
footgun. Never reintroduce offset-based IDs.

**The embedding model loads in the Celery worker, not the API.** Keeps the API light. `get_model()`
is a lazy singleton — don't move model loading into the request path or into API startup.

**`src/eda/` stays framework-agnostic.** It must not import from `api/`. Parsers and indexing are
reused by both scripts and the API; keeping them clean is what let the upload feature reuse them.

**Language is detected per-chunk, not per-tenant.** A single file can mix Persian and English.
`lang` is set on each Chunk via `persian_ratio`.

**Normalize Persian before measuring or matching.** Two Unicode families exist in the corpus
(standard Arabic block vs. presentation forms). Metrics computed on un-normalized text lie.

---

## Current state

Working and verified: RAG pipeline, eval harness, multi-tenancy with adversarial leak suite
(0/20 leaks, negative control confirms the test can fail), dynamic RBAC, React frontend, Docker
(one-command start, Qdrant as server), async document upload via Celery.

Known tech debt (see README):
- `SECRET_KEY` should come from env in all environments, not a config default.
- Permissions are baked into the JWT — a revoked permission stays live until token expiry (60m).
- `eval.py` still targets the old `"postgres"` collection and pre-multi-tenant ground-truth IDs;
  it is broken against the current `"docs"` layout and needs remapping before its numbers mean
  anything again.

---

## Testing conventions

Run the app from the project root, never from a subdirectory (relative paths assume root).
Services expected up for full testing: Qdrant, Redis, Celery worker, the API, and Ollama on the
host with `llama3.1:8b-local`.

When verifying a change to retrieval or auth, the canonical check is: `sara` and `reza` (same
tenant `kb`, different groups) asking the same billing question must return non-overlapping
sources; `maryam` (level `user`) must get 403 on `/admin/*` and a working `/ask`.