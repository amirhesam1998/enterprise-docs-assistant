"""Deterministic identifiers for ingestion entities.

The helpers use UUID5 so identifiers reveal neither document text nor hashes.
Stability depends on callers providing the same normalized tenant/logical key,
content hash, page index, layer/route, and deterministic order.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from pathlib import Path


PROJECT_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS,
    "enterprise-docs-assistant",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: str | Path, block_size: int = 1024 * 1024) -> str:
    """Return the lowercase SHA-256 digest without loading the file at once."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_sha256(value: str) -> str:
    """Normalize and validate a hexadecimal SHA-256 digest."""
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError("Expected a 64-character hexadecimal SHA-256 digest.")
    return normalized


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    text = " ".join(text.split())
    if not text:
        raise ValueError("Identifier inputs must not be empty.")
    return text


def _uuid(kind: str, *parts: object) -> str:
    name = "\x1f".join((_normalize(kind), *(_normalize(part) for part in parts)))
    return str(uuid.uuid5(PROJECT_NAMESPACE, name))


def document_id(tenant_id: str, logical_key: str) -> str:
    """Return a tenant-scoped logical document ID.

    ``logical_key`` must be an authoritative stable key (for example a DMS ID),
    not merely a filename. Different tenants cannot collide for the same key.
    """
    return _uuid("document", tenant_id, logical_key)


def revision_id(logical_document_id: str, source_sha256: str) -> str:
    """Return a revision ID that changes whenever source content changes."""
    return _uuid("revision", logical_document_id, validate_sha256(source_sha256))


def page_id(document_revision_id: str, page_index: int) -> str:
    """Return a page ID from a revision and zero-based internal page index."""
    if page_index < 0:
        raise ValueError("page_index must be zero or greater.")
    return _uuid("page", document_revision_id, page_index)


def region_id(
    document_page_id: str,
    source_layer: str,
    route: str,
    reading_order: int,
) -> str:
    """Return a region ID from page, layer/route, and deterministic order."""
    if reading_order < 0:
        raise ValueError("reading_order must be zero or greater.")
    return _uuid(
        "region",
        document_page_id,
        source_layer,
        route,
        reading_order,
    )


def block_id(
    document_page_id: str,
    block_type: str,
    reading_order: int,
) -> str:
    """Return a block ID from page, semantic block type, and deterministic order.

    Blocks are the semantic units (heading, paragraph, table, ...) sitting a level
    above raw regions. The ``reading_order`` keeps sibling blocks of the same type
    distinct and stable across re-ingestion of identical content.
    """
    if reading_order < 0:
        raise ValueError("reading_order must be zero or greater.")
    return _uuid("block", document_page_id, block_type, reading_order)


def chunk_id(
    document_page_id: str,
    chunk_index: int,
    strategy: str = "structural-v1",
) -> str:
    """Return the stable chunk-ID foundation for the later chunking milestone."""
    if chunk_index < 0:
        raise ValueError("chunk_index must be zero or greater.")
    return _uuid("chunk", document_page_id, strategy, chunk_index)
