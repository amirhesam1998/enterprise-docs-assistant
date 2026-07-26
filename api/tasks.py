"""Ingestion tasks. These run in the Celery worker, never in the API process.

The embedding model is ~2GB and is loaded lazily by eda.index inside whichever
process calls ingest_chunks — keeping ingestion here means the API never pays
that cost and never blocks a request on it.

Identity (tenant_id + acl_groups) is passed in by the caller and is always taken
from the uploader's token. This task re-stamps every parsed chunk with it, so
nothing a *file* claims about its own access control can override who the
uploader actually is.
"""
from qdrant_client import QdrantClient
from api.celery_app import celery_app
from api.config import QDRANT_COLLECTION, QDRANT_URL
from eda.index import ingest_chunks
from eda.parse import parse_any


def _stamp_identity(chunks, tenant_id: str, acl_groups: list[str]):
    """Force the uploader's identity onto every chunk.

    parse_xlsx reads ACL groups out of a column in the sheet — correct for the
    curated batch index (build_index.py), wrong for an upload, where the file is
    untrusted input and would otherwise let an uploader grant themselves any
    group. The token wins here.

    chunk_id is also namespaced by tenant: eda.index derives its point ID from
    uuid5(NAMESPACE, chunk_id), and the raw IDs are only unique per filename, so
    two tenants uploading "report.pdf" would otherwise overwrite each other's
    points. Prefixing keeps re-uploading the *same* file by the *same* tenant
    idempotent, which is the property the uuid5 scheme exists to provide.
    """
    for c in chunks:
        c.tenant_id = tenant_id
        c.acl_groups = list(acl_groups)
        c.chunk_id = f"{tenant_id}:{c.chunk_id}"
    return chunks



@celery_app.task(bind=True)
def ingest_document(self, path, tenant_id, source, acl_groups):
    chunks = parse_any(path, tenant_id, source, acl_groups=acl_groups)
    chunks = _stamp_identity(chunks, tenant_id, acl_groups)   # ← برگردون
    client = QdrantClient(url=QDRANT_URL)
    try:
        n = ingest_chunks(chunks, client, QDRANT_COLLECTION)
    finally:
        client.close()
    # tenant_id is echoed back so /documents/jobs/{id} can scope a result to the
    # caller's tenant instead of handing any job's outcome to any admin.
    return {"chunks": n, "source": source, "tenant_id": tenant_id}
