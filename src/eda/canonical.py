"""Builders that turn extractor output into schema-valid canonical objects.

This module is deliberately framework-agnostic and free of OCR/runtime coupling:
it only constructs `DocumentManifest`, `PageResult`, and `BlockResult` instances
that satisfy the invariants declared in `eda.ingestion_schema`. Extractors supply
the already-decided status/route; the quality scorer decides those upstream so
low-quality extraction is never silently marked accepted here.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from eda.identifiers import (
    block_id as build_block_id,
    document_id as build_document_id,
    page_id as build_page_id,
    revision_id as build_revision_id,
    sha256_file,
)
from eda.ingestion_schema import (
    BlockResult,
    BlockType,
    DocumentManifest,
    ExtractionRoute,
    OCRDecision,
    PageResult,
    PageType,
    ProcessingProvenance,
    ProcessingStatus,
    TableCell,
    TableResult,
    TextLayer,
    safe_git_revision,
)
from eda.normalize import persian_ratio


def detect_block_language(text: str) -> str:
    """Return a per-block ``fa``/``en`` label, matching the Chunk convention."""
    return "fa" if persian_ratio(text) > 0.5 else "en"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def lightweight_provenance(
    *,
    digest: str,
    pipeline_name: str,
    pipeline_version: str,
    timestamp: datetime | None = None,
    dpi: int | None = None,
    resolved_language_profiles: Iterable[str] = (),
) -> ProcessingProvenance:
    """Provenance for text extractors that do not shell out to Tesseract."""
    return ProcessingProvenance(
        pipeline_name=pipeline_name,
        pipeline_version=pipeline_version,
        input_sha256=digest,
        dpi=dpi,
        resolved_language_profiles=list(resolved_language_profiles),
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} {platform.machine()}".strip(),
        code_revision=safe_git_revision(),
        processing_timestamp=timestamp or utc_now(),
    )


def build_manifest(
    *,
    path: str | Path,
    tenant_id: str,
    logical_document_key: str,
    source_name: str,
    source_type: str,
    mime_type: str,
    parser_name: str,
    parser_version: str,
    total_pages: int | None,
    timestamp: datetime | None = None,
    digest: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> DocumentManifest:
    """Build a public manifest with deterministic tenant-scoped identities."""
    source_path = Path(path)
    digest = digest or sha256_file(source_path)
    logical_id = build_document_id(tenant_id, logical_document_key)
    revision = build_revision_id(logical_id, digest)
    metadata = dict(extra_metadata or {})
    return DocumentManifest(
        document_id=logical_id,
        revision_id=revision,
        tenant_id=tenant_id,
        source_name=Path(source_name).name,
        source_type=source_type,
        source_sha256=digest,
        file_size_bytes=source_path.stat().st_size,
        mime_type=mime_type,
        total_pages=total_pages,
        parser_name=parser_name,
        parser_version=parser_version,
        created_at=timestamp or utc_now(),
        metadata=metadata,
    )


def build_table(
    rows: list[list[str]],
    *,
    caption: str | None = None,
    header_rows: int = 1,
) -> TableResult | None:
    """Build a canonical `TableResult` from a row-major grid of cell strings.

    Returns ``None`` when the grid has no columns. ``markdown`` is a lossy pipe
    rendering used only as a reading aid — the structured cells are authoritative.
    """
    rows = [[("" if value is None else str(value)).strip() for value in row] for row in rows]
    num_cols = max((len(row) for row in rows), default=0)
    if num_cols == 0 or not rows:
        return None
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        for col_index in range(num_cols):
            text = row[col_index] if col_index < len(row) else ""
            cells.append(
                TableCell(
                    row_index=row_index,
                    col_index=col_index,
                    text=text,
                    is_header=row_index < header_rows,
                )
            )
    return TableResult(
        num_rows=len(rows),
        num_cols=num_cols,
        cells=cells,
        caption=caption,
        markdown=table_markdown(rows, header_rows=header_rows),
    )


def table_markdown(rows: list[list[str]], *, header_rows: int = 1) -> str:
    """Render a grid as GitHub-flavored Markdown for human-readable previews."""
    if not rows:
        return ""
    num_cols = max(len(row) for row in rows)

    def render(row: list[str]) -> str:
        padded = [str(row[index]).replace("|", "\\|") if index < len(row) else "" for index in range(num_cols)]
        return "| " + " | ".join(padded) + " |"

    lines = [render(rows[0])]
    if header_rows >= 1:
        lines.append("| " + " | ".join(["---"] * num_cols) + " |")
    lines.extend(render(row) for row in rows[1:])
    return "\n".join(lines)


def table_reading_text(table: TableResult) -> str:
    """Flatten a table into retrieval text preserving row/column context.

    Each data row becomes ``header: value`` pairs so an embedding of a table row
    keeps the column semantics that a blind flatten would discard.
    """
    grid: dict[tuple[int, int], str] = {}
    for cell in table.cells:
        grid[(cell.row_index, cell.col_index)] = cell.text
    headers = [grid.get((0, col), f"col{col + 1}") for col in range(table.num_cols)]
    lines: list[str] = []
    if table.caption:
        lines.append(table.caption)
    for row in range(1, table.num_rows):
        pairs = [
            f"{headers[col]}: {grid.get((row, col), '')}".strip()
            for col in range(table.num_cols)
            if grid.get((row, col), "").strip()
        ]
        if pairs:
            lines.append(" | ".join(pairs))
    return "\n".join(lines) if lines else (table.markdown or table.caption or "")


def make_block(
    *,
    page_id: str,
    page_number: int,
    block_type: BlockType,
    text: str,
    reading_order: int,
    source_layer: TextLayer,
    extraction_route: ExtractionRoute,
    bbox: tuple[float, float, float, float] | None = None,
    confidence: float | None = None,
    quality_score: float | None = None,
    table: TableResult | None = None,
    metadata: dict[str, Any] | None = None,
) -> BlockResult:
    """Create one canonical block with a deterministic, page-scoped ``block_id``."""
    return BlockResult(
        block_id=build_block_id(page_id, block_type.value, reading_order),
        block_type=block_type,
        text=text,
        page_number=page_number,
        reading_order=reading_order,
        source_layer=source_layer,
        extraction_route=extraction_route,
        bbox=bbox,
        language_profile=detect_block_language(text),
        confidence=confidence,
        quality_score=quality_score,
        table=table,
        metadata=dict(metadata or {}),
    )


def native_page_result(
    *,
    manifest: DocumentManifest,
    page_index: int,
    native_text: str,
    provenance: ProcessingProvenance,
    blocks: list[BlockResult] | None = None,
    processing_status: ProcessingStatus,
    quality_gate_passed: bool,
    quality_score: float | None = None,
    page_type: PageType = PageType.DIGITAL,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PageResult:
    """Assemble a digital/native page for text-first extractors (PDF, DOCX, XLSX)."""
    document_page_id = build_page_id(str(manifest.revision_id), page_index)
    has_text = bool(native_text.strip())
    if has_text:
        route = ExtractionRoute.NATIVE
    else:
        route = ExtractionRoute.REJECTED
        page_type = PageType.EMPTY
        if processing_status == ProcessingStatus.ACCEPTED:
            processing_status = ProcessingStatus.FAILED
        quality_gate_passed = False
    return PageResult(
        document_id=manifest.document_id,
        revision_id=manifest.revision_id,
        page_id=document_page_id,
        page_index=page_index,
        page_number=page_index + 1,
        page_type=page_type,
        processing_status=processing_status,
        native_text=native_text,
        ocr_text="",
        blocks=blocks or [],
        ocr_decision=OCRDecision(
            quality_score=quality_score,
            selected_route=route,
            quality_gate_passed=quality_gate_passed,
            candidate_count=0,
        ),
        provenance=provenance,
        warnings=warnings or [],
        errors=errors or [],
    )


def ocr_page_result(
    *,
    manifest: DocumentManifest,
    page_index: int,
    ocr_text: str,
    provenance: ProcessingProvenance,
    blocks: list[BlockResult] | None = None,
    processing_status: ProcessingStatus,
    quality_gate_passed: bool,
    mean_confidence: float | None = None,
    quality_score: float | None = None,
    language_profile: str | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PageResult:
    """Assemble a scanned/full-page-OCR page for single-image extraction."""
    document_page_id = build_page_id(str(manifest.revision_id), page_index)
    has_text = bool(ocr_text.strip())
    if has_text:
        route = ExtractionRoute.FULL_PAGE_OCR
        page_type = PageType.SCANNED
        candidate_count = 1
    else:
        route = ExtractionRoute.REJECTED
        page_type = PageType.EMPTY
        candidate_count = 0
        if processing_status == ProcessingStatus.ACCEPTED:
            processing_status = ProcessingStatus.FAILED
        quality_gate_passed = False
    return PageResult(
        document_id=manifest.document_id,
        revision_id=manifest.revision_id,
        page_id=document_page_id,
        page_index=page_index,
        page_number=page_index + 1,
        page_type=page_type,
        processing_status=processing_status,
        native_text="",
        ocr_text=ocr_text,
        blocks=blocks or [],
        ocr_decision=OCRDecision(
            mean_confidence=mean_confidence,
            quality_score=quality_score,
            selected_route=route,
            selected_language_profile=language_profile,
            quality_gate_passed=quality_gate_passed,
            candidate_count=candidate_count,
        ),
        provenance=provenance,
        warnings=warnings or [],
        errors=errors or [],
    )
