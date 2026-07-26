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
