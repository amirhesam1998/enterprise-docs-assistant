"""Compatibility adapter from typed pages to the legacy page-sized Chunk."""

from __future__ import annotations

from eda.identifiers import chunk_id as build_chunk_id
from eda.ingestion_schema import DocumentManifest, PageResult, ProcessingStatus
from eda.normalize import persian_ratio
from eda.schema import Chunk


def _require_groups(groups: list[str] | None) -> list[str]:
    if not groups:
        raise ValueError("Adaptive PDF ingestion requires explicit non-empty ACL groups.")
    normalized: list[str] = []
    for group in groups:
        if not isinstance(group, str) or not group.strip():
            raise ValueError("ACL groups must be non-empty strings.")
        group = group.strip()
        if group not in normalized:
            normalized.append(group)
    return normalized


def page_result_to_chunk(
    page: PageResult,
    manifest: DocumentManifest,
    *,
    acl_groups: list[str] | None,
    allow_needs_review: bool = False,
) -> Chunk:
    """Create one page-sized compatibility chunk; structural chunking comes later."""
    groups = _require_groups(acl_groups)
    if str(page.document_id) != str(manifest.document_id) or str(page.revision_id) != str(manifest.revision_id):
        raise ValueError("Page and manifest identities do not match.")
    if page.processing_status == ProcessingStatus.FAILED:
        raise ValueError("Failed pages cannot be converted to chunks.")
    if page.processing_status == ProcessingStatus.NEEDS_REVIEW and not allow_needs_review:
        raise ValueError("needs_review pages require explicit allow_needs_review=True.")
    text = page.index_text.strip()
    if not text:
        raise ValueError("Empty page index text cannot be converted to a chunk.")

    return Chunk(
        text=text,
        lang="fa" if persian_ratio(text) > 0.5 else "en",
        tenant_id=manifest.tenant_id,
        source=manifest.source_name,
        source_type="pdf",
        location={
            "type": "page",
            "num": page.page_number,
            "page_id": str(page.page_id),
            "document_id": str(page.document_id),
            "revision_id": str(page.revision_id),
            "provenance": {
                "pipeline_name": page.provenance.pipeline_name,
                "pipeline_version": page.provenance.pipeline_version,
                "schema_version": page.schema_version,
            },
        },
        acl_groups=groups,
        chunk_id=build_chunk_id(str(page.page_id), 0, strategy="page-v1"),
    )


def extraction_to_chunks(
    pages: list[PageResult] | tuple[PageResult, ...],
    manifest: DocumentManifest,
    *,
    acl_groups: list[str] | None,
    allow_needs_review: bool = False,
) -> list[Chunk]:
    return [
        page_result_to_chunk(
            page,
            manifest,
            acl_groups=acl_groups,
            allow_needs_review=allow_needs_review,
        )
        for page in pages
    ]
