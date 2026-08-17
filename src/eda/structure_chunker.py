"""Structure-aware chunking from canonical blocks to legacy `Chunk`s.

This is the bridge from the modern canonical representation to the existing
`eda.index.ingest_chunks()` path: it walks accepted pages, groups reading-ordered
blocks into word-budgeted chunks (headings lead their section, tables become their
own chunk with preserved row/column context), and stamps every chunk with full
provenance — document/revision/page/block IDs, extraction route, quality score,
tenant, and ACL groups.

Two invariants it never breaks:
  * ACL groups are required and authoritative; they are never read from content.
  * Failed pages — and needs_review pages unless explicitly allowed — are never
    converted to embeddable chunks.
"""

from __future__ import annotations

from eda.chunk import split_fixed
from eda.extractors.base import ExtractedDocument, ExtractionOptions
from eda.identifiers import chunk_id as build_chunk_id
from eda.ingestion_schema import BlockResult, BlockType, PageResult, ProcessingStatus
from eda.normalize import persian_ratio
from eda.quality import PageQuality
from eda.schema import Chunk

DEFAULT_MAX_WORDS = 350


def _require_groups(groups) -> list[str]:
    if not groups:
        raise ValueError("Structure-aware chunking requires explicit non-empty ACL groups.")
    normalized: list[str] = []
    for group in groups:
        if not isinstance(group, str) or not group.strip():
            raise ValueError("ACL groups must be non-empty strings.")
        group = group.strip()
        if group not in normalized:
            normalized.append(group)
    return normalized


def _lang(text: str) -> str:
    return "fa" if persian_ratio(text) > 0.5 else "en"


def _word_count(text: str) -> int:
    return len(text.split())


def _base_location(
    document: ExtractedDocument,
    page: PageResult,
    quality: PageQuality | None,
) -> dict:
    return {
        "type": "page",
        "num": page.page_number,
        "page_id": str(page.page_id),
        "document_id": str(page.document_id),
        "revision_id": str(page.revision_id),
        "source_type": document.manifest.source_type,
        "extractor_route": document.extractor_route.value,
        "route": page.ocr_decision.selected_route.value,
        "quality_score": quality.score if quality else None,
        "strategy": "structural-v1",
    }


def _make_chunk(
    document: ExtractedDocument,
    page: PageResult,
    quality: PageQuality | None,
    *,
    text: str,
    chunk_index: int,
    acl_groups: list[str],
    block_ids: list[str],
    kind: str = "text",
) -> Chunk:
    location = _base_location(document, page, quality)
    location["block_ids"] = block_ids
    location["kind"] = kind
    return Chunk(
        text=text,
        lang=_lang(text),
        tenant_id=document.manifest.tenant_id,
        source=document.manifest.source_name,
        source_type=document.manifest.source_type,
        location=location,
        acl_groups=list(acl_groups),
        chunk_id=build_chunk_id(str(page.page_id), chunk_index, strategy="structural-v1"),
    )


def _page_chunks(
    document: ExtractedDocument,
    page: PageResult,
    quality: PageQuality | None,
    acl_groups: list[str],
    max_words: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    index = 0

    def emit(text: str, block_ids: list[str], kind: str) -> None:
        nonlocal index
        text = text.strip()
        if not text:
            return
        chunks.append(
            _make_chunk(
                document, page, quality, text=text, chunk_index=index,
                acl_groups=acl_groups, block_ids=block_ids, kind=kind,
            )
        )
        index += 1

    # No canonical blocks (e.g. the adaptive OCR route): fall back to fixed-size
    # splitting over the page's deduplicated index text.
    if not page.blocks:
        for piece in split_fixed(page.index_text):
            emit(piece, [], "text")
        return chunks

    group_parts: list[str] = []
    group_block_ids: list[str] = []
    group_words = 0

    def flush_group() -> None:
        nonlocal group_parts, group_block_ids, group_words
        if group_parts:
            emit("\n\n".join(group_parts), list(group_block_ids), "text")
        group_parts = []
        group_block_ids = []
        group_words = 0

    for block in page.blocks:
        if block.block_type == BlockType.TABLE:
            flush_group()
            _emit_table(block, emit, max_words)
            continue
        words = _word_count(block.text)
        if block.block_type == BlockType.HEADING and group_parts:
            # A heading opens a new section: flush what precedes it.
            flush_group()
        if group_words and group_words + words > max_words:
            flush_group()
        if words > max_words:
            # A single oversized block is split, but kept out of a shared group.
            flush_group()
            for piece in split_fixed(block.text, max_words):
                emit(piece, [str(block.block_id)], "text")
            continue
        group_parts.append(block.text)
        group_block_ids.append(str(block.block_id))
        group_words += words
    flush_group()
    return chunks


def _emit_table(block: BlockResult, emit, max_words: int) -> None:
    """Emit a table as its own chunk(s), preserving row/column context text."""
    if _word_count(block.text) <= max_words:
        emit(block.text, [str(block.block_id)], "table")
        return
    for piece in split_fixed(block.text, max_words):
        emit(piece, [str(block.block_id)], "table")


def structure_chunks(
    document: ExtractedDocument,
    *,
    acl_groups,
    allow_needs_review: bool = False,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[Chunk]:
    """Convert accepted canonical pages into ACL-stamped, provenance-rich chunks."""
    groups = _require_groups(acl_groups)
    quality_by_page = {pq.page_number: pq for pq in document.quality.page_qualities}

    chunks: list[Chunk] = []
    for page in document.pages:
        if page.processing_status == ProcessingStatus.FAILED:
            continue
        if page.processing_status == ProcessingStatus.NEEDS_REVIEW and not allow_needs_review:
            continue
        chunks.extend(
            _page_chunks(document, page, quality_by_page.get(page.page_number), groups, max_words)
        )
    return chunks


def extract_document_chunks(
    path,
    *,
    tenant_id: str,
    logical_document_key: str,
    source_name: str,
    acl_groups,
    router=None,
    allow_needs_review: bool = False,
    max_words: int = DEFAULT_MAX_WORDS,
) -> tuple[ExtractedDocument, list[Chunk]]:
    """Route → extract → quality-score → structure-chunk in one call.

    The clean seam for wiring the canonical pipeline into Celery later without
    changing the current default ingestion path. ACL groups come from the
    authenticated uploader and are authoritative for both extraction and chunking.
    """
    from eda.extractors.router import default_router

    router = router or default_router()
    options = ExtractionOptions(
        tenant_id=tenant_id,
        logical_document_key=logical_document_key,
        source_name=source_name,
        acl_groups=tuple(acl_groups or ()),
        allow_needs_review=allow_needs_review,
    )
    document = router.extract(path, options=options)
    chunks = structure_chunks(
        document, acl_groups=acl_groups, allow_needs_review=allow_needs_review, max_words=max_words,
    )
    return document, chunks
