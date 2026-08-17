"""Runtime configuration, all overridable via environment variables.

Nothing secret is hardcoded for production use — the defaults exist so the demo
runs out of the box. Override SECRET_KEY and the creator credentials in any real
deployment.
"""
import os

# --- JWT ---
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
ALGORITHM = "HS256"
# Short lifetime is deliberate: permissions are baked into the token (see auth.py),
# so a revocation only takes effect once the token expires. 60 minutes bounds that
# staleness window.
TOKEN_MINUTES = int(os.getenv("TOKEN_MINUTES", "60"))

# --- Database ---
DB_PATH = os.getenv("APP_DB_PATH", "data/app.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# --- Signup / seeding ---
# Tenant assigned to every self-registered user. They can never pick their own.
DEFAULT_TENANT = os.getenv("DEFAULT_TENANT", "public")

# Seeded bootstrap creator. There is always at least one creator in the system.
CREATOR_USERNAME = os.getenv("CREATOR_USERNAME", "creator")
CREATOR_PASSWORD = os.getenv("CREATOR_PASSWORD", "creator123")
CREATOR_EMAIL = os.getenv("CREATOR_EMAIL", "creator@example.com")

# --- CORS ---
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

# --- Retrieval backends ---
# Qdrant runs as a server (never embedded file mode — that takes an exclusive
# lock and stops the API and the indexing scripts from running at the same time).
# The default points at a server on the host so scripts work outside Docker;
# compose overrides it with the internal service name.
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")

# Ollama deliberately stays outside Docker. From inside a container the host is
# reachable as host.docker.internal (Docker Desktop); that name also resolves on
# the host itself, so this default works in both places.
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b-local")

# --- Async ingestion (Celery) ---
# Broker and result backend for the ingestion worker. The default points at a
# server on the host so a worker can be run outside Docker; compose overrides it
# with the internal service name.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Uploaded files land here. It sits under data/ on purpose: that directory is the
# shared mount, so the API writes the file and the worker reads the same path.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")


# --- Ingestion pipeline selection ---
# The worker can ingest through the legacy parser path or the new canonical,
# route-based extraction pipeline. The switch is a single environment variable and
# defaults to legacy — current behavior is preserved unless explicitly opted in.
# Invalid values fail loudly here at import (startup), not silently at runtime.
def _env_choice(name: str, default: str, allowed: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in allowed:
        raise ValueError(
            f"{name} must be one of {sorted(allowed)}; got {os.getenv(name)!r}."
        )
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false); got {raw!r}.")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer; got {raw!r}.") from error
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}; got {value}.")
    return value


INGESTION_PIPELINES = {"legacy", "canonical", "docling_first"}

# legacy        : parse_any() -> _stamp_identity() -> ingest_chunks()  (unchanged)
# canonical     : route-based canonical extraction + quality gating (default_router)
# docling_first : same as canonical but prefers Docling for PDF/DOCX
INGESTION_PIPELINE = _env_choice("INGESTION_PIPELINE", "legacy", INGESTION_PIPELINES)

# Canonical only: embed pages the quality gate flagged for review. Off by default —
# needs_review is reported as a business outcome, not silently indexed.
INGESTION_ALLOW_NEEDS_REVIEW = _env_bool("INGESTION_ALLOW_NEEDS_REVIEW", False)

# Canonical only: word budget for structure-aware chunking (structure_chunker's
# DEFAULT_MAX_WORDS). Kept here so it is tunable without touching library code.
INGESTION_MAX_CHUNK_WORDS = _env_int("INGESTION_MAX_CHUNK_WORDS", 350)

# Canonical only: when extraction yields zero embeddable chunks and there is no
# needs_review outcome (i.e. everything failed), fail the task loudly instead of
# reporting a silent success.
INGESTION_FAIL_ON_ZERO_CHUNKS = _env_bool("INGESTION_FAIL_ON_ZERO_CHUNKS", True)
