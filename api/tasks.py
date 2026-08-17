"""Ingestion tasks. These run in the Celery worker, never in the API process.

The embedding model is ~2GB and is loaded lazily by eda.index inside whichever
process calls ingest_chunks — keeping ingestion here means the API never pays
that cost and never blocks a request on it.

Identity (tenant_id + acl_groups) is passed in by the caller and is always taken
from the uploader's token. This task re-stamps every parsed chunk with it, so
nothing a *file* claims about its own access control can override who the
uploader actually is.

Two ingestion pipelines are available, selected by config.INGESTION_PIPELINE:

  * legacy        — parse_any() -> _stamp_identity() -> ingest_chunks() (default,
                    behavior preserved exactly).
  * canonical /   — route-based canonical extraction with quality gating; only
    docling_first   accepted content is embedded, and the job result carries the
                    extraction/quality details.

The switch is reversible: set INGESTION_PIPELINE=legacy to roll back instantly.
"""
from pathlib import Path

from qdrant_client import QdrantClient

from api import config
from api.celery_app import celery_app
from api.config import QDRANT_COLLECTION, QDRANT_URL
from eda.extractors.router import default_router, docling_first_router
from eda.index import ingest_chunks
from eda.parse import parse_any
from eda.structure_chunker import extract_document_chunks


class IngestionError(RuntimeError):
    """A deliberate, public-safe ingestion failure (not an infrastructure crash)."""


def _stamp_identity(chunks, tenant_id: str, acl_groups: list[str]):
    """Force the uploader's identity onto every chunk.

    parse_xlsx requires an explicit ACL scope and never reads access control from
    an untrusted workbook. Re-stamping here keeps the token authoritative for all
    parsers and protects future parser changes from weakening that boundary.

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


def _resolve_pipeline() -> str:
    """Read and validate the configured pipeline at task time (fails loudly)."""
    value = str(getattr(config, "INGESTION_PIPELINE", "legacy")).strip().lower()
    if value not in config.INGESTION_PIPELINES:
        raise ValueError(
            f"INGESTION_PIPELINE must be one of {sorted(config.INGESTION_PIPELINES)}; "
            f"got {getattr(config, 'INGESTION_PIPELINE', None)!r}."
        )
    return value


@celery_app.task(bind=True)
def ingest_document(self, path, tenant_id, source, acl_groups):
    pipeline = _resolve_pipeline()
    if pipeline == "legacy":
        return _ingest_legacy(path, tenant_id, source, acl_groups)
    router = docling_first_router() if pipeline == "docling_first" else default_router()
    return _ingest_canonical(path, tenant_id, source, acl_groups, router=router, pipeline=pipeline)


# --------------------------------------------------------------------------- #
# Legacy path — preserved exactly.
# --------------------------------------------------------------------------- #
def _ingest_legacy(path, tenant_id, source, acl_groups):
    parse_options = (
        {"logical_document_key": Path(path).name}
        if Path(path).suffix.casefold() == ".pdf"
        else {}
    )
    chunks = parse_any(path, tenant_id, source, acl_groups=acl_groups, **parse_options)
    chunks = _stamp_identity(chunks, tenant_id, acl_groups)
    client = QdrantClient(url=QDRANT_URL)
    try:
        n = ingest_chunks(chunks, client, QDRANT_COLLECTION)
    finally:
        client.close()
    # tenant_id is echoed back so /documents/jobs/{id} can scope a result to the
    # caller's tenant instead of handing any job's outcome to any admin.
    return {"chunks": n, "source": source, "tenant_id": tenant_id}


# --------------------------------------------------------------------------- #
# Canonical path — route-based extraction, quality-gated, only accepted content
# is embedded.
# --------------------------------------------------------------------------- #
def _ingest_canonical(path, tenant_id, source, acl_groups, *, router, pipeline):
    # logical_document_key = the display filename, matching legacy idempotency:
    # same tenant + same filename -> same deterministic IDs -> overwrite, not
    # duplicate. tenant/ACL are the uploader's, never read from the document.
    document, chunks = extract_document_chunks(
        path,
        tenant_id=tenant_id,
        logical_document_key=source,
        source_name=source,
        acl_groups=acl_groups,
        router=router,
        allow_needs_review=config.INGESTION_ALLOW_NEEDS_REVIEW,
        max_words=config.INGESTION_MAX_CHUNK_WORDS,
    )
    chunks = _stamp_identity(chunks, tenant_id, acl_groups)

    embedded = 0
    if chunks:
        client = QdrantClient(url=QDRANT_URL)
        try:
            embedded = ingest_chunks(chunks, client, QDRANT_COLLECTION)
        finally:
            client.close()

    result = _canonical_result(document, embedded, pipeline, source, tenant_id)

    # A genuinely empty extraction (nothing accepted, nothing to review) is a
    # deliberate, loud failure by default — never a silent "success" that indexed
    # nothing. needs_review, by contrast, stays a SUCCESS business outcome.
    if (
        embedded == 0
        and result["ingestion_status"] == "failed"
        and config.INGESTION_FAIL_ON_ZERO_CHUNKS
    ):
        raise IngestionError(
            f"Extraction produced no embeddable content for {source!r} "
            f"(route={result['extraction_route']}, quality={result['quality_level']}). "
            "Nothing was indexed."
        )
    return result


def _canonical_result(document, embedded, pipeline, source, tenant_id):
    quality = document.quality
    warnings = list(document.warnings) + list(quality.warnings)
    if embedded > 0:
        clean = (
            quality.level.value == "accepted"
            and not warnings
            and quality.needs_review_pages == 0
        )
        status = "indexed" if clean else "indexed_with_warnings"
    elif quality.needs_review_pages > 0:
        status = "needs_review"
    else:
        status = "failed"

    return {
        # Backward-compatible fields (same keys the legacy result and frontend use).
        "chunks": embedded,
        "source": source,
        "tenant_id": tenant_id,
        # Canonical extras.
        "ingestion_pipeline": pipeline,
        "extraction_route": document.extractor_route.value,
        "ingestion_status": status,
        "quality_score": quality.score,
        "quality_level": quality.level.value,
        "total_pages": quality.total_pages,
        "accepted_pages": quality.accepted_pages,
        "needs_review_pages": quality.needs_review_pages,
        "failed_pages": quality.failed_pages,
        "empty_pages": quality.empty_pages,
        "table_count": document.table_count,
        "warnings": warnings,
        "errors": list(document.errors),
        "embedded_chunks": embedded,
    }
