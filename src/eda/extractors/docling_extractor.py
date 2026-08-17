"""Docling-backed extractor for digital PDFs and DOCX.

Docling is a modern, layout- and table-aware conversion engine. It is used here
as one candidate *behind the extractor interface* — never coupled into the rest
of the pipeline. The engine is imported lazily and, if unavailable or unable to
convert, the extractor raises a public-safe error so the router can fall back to
the native/adaptive routes.

The Docling document model varies across releases, so the mapping to canonical
blocks is deliberately defensive (string labels, guarded attribute access). Block
bounding boxes are intentionally left unset: Docling coordinate origins differ by
backend, and an incorrect box is worse than none. This adapter still needs
validation against real Persian/English documents.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from eda.canonical import (
    build_manifest,
    build_table,
    lightweight_provenance,
    make_block,
    native_page_result,
    table_reading_text,
)
from eda.identifiers import page_id as build_page_id, sha256_file
from eda.ingestion_schema import BlockType, ExtractionRoute, TextLayer
from eda.ocr_quality import normalize_ocr_text
from eda.quality import level_for_score, score_text, to_processing_status
from eda.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorRoute,
    ExtractorUnavailable,
)

PARSER_NAME = "docling"
PARSER_VERSION = "1.0"

_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

_LABEL_TO_BLOCK = {
    "title": BlockType.HEADING,
    "section_header": BlockType.HEADING,
    "subtitle": BlockType.HEADING,
    "paragraph": BlockType.PARAGRAPH,
    "text": BlockType.PARAGRAPH,
    "list_item": BlockType.LIST_ITEM,
    "caption": BlockType.CAPTION,
    "page_header": BlockType.HEADER,
    "page_footer": BlockType.FOOTER,
    "footnote": BlockType.FOOTER,
    "key_value_region": BlockType.KEY_VALUE,
}


def docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


def _label_value(item) -> str:
    label = getattr(item, "label", None)
    return str(getattr(label, "value", label) or "").lower()


def _page_no(item) -> int:
    prov = getattr(item, "prov", None) or []
    for entry in prov:
        page_no = getattr(entry, "page_no", None)
        if isinstance(page_no, int) and page_no > 0:
            return page_no
    return 1


def _table_rows(item) -> list[list[str]] | None:
    """Best-effort extraction of a row-major grid from a Docling table item."""
    data = getattr(item, "data", None)
    grid = getattr(data, "grid", None)
    if grid:
        rows = []
        for grid_row in grid:
            rows.append([str(getattr(cell, "text", "") or "") for cell in grid_row])
        if any(any(cell.strip() for cell in row) for row in rows):
            return rows
    export = getattr(item, "export_to_dataframe", None)
    if callable(export):
        try:
            frame = export()
            header = [str(column) for column in frame.columns]
            body = [[str(value) for value in row] for row in frame.itertuples(index=False, name=None)]
            return [header, *body]
        except Exception:  # noqa: BLE001 - fall through to caller's fallback
            return None
    return None


def _convert(source: Path):
    try:
        from docling.document_converter import DocumentConverter
    except Exception as error:  # noqa: BLE001 - import-time failures are "unavailable"
        raise ExtractorUnavailable("Docling is not installed or failed to import.") from error
    try:
        result = DocumentConverter().convert(str(source))
    except Exception as error:  # noqa: BLE001 - message intentionally path-free
        raise ExtractionFailed("Docling conversion failed.") from error
    document = getattr(result, "document", None)
    if document is None:
        raise ExtractionFailed("Docling returned no document.")
    return document


class DoclingExtractor(DocumentExtractor):
    route = ExtractorRoute.DOCLING
    supported_extensions = frozenset({".pdf", ".docx"})

    def supports(self, path, mime_type=None, extension=None) -> bool:
        # Advertise support even when the engine is missing: the router will call
        # extract(), receive ExtractorUnavailable, and record a clean fallback.
        return super().supports(path, mime_type, extension)

    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        source = Path(path)
        if not source.is_file():
            raise ExtractionFailed("Source is unavailable or unreadable.")
        if not docling_available():
            raise ExtractorUnavailable("Docling is not installed.")
        digest = sha256_file(source)
        document = _convert(source)

        pages_attr = getattr(document, "pages", None)
        total_pages = len(pages_attr) if pages_attr else None

        ext = source.suffix.lower()
        manifest = build_manifest(
            path=source,
            tenant_id=options.tenant_id,
            logical_document_key=options.logical_document_key,
            source_name=options.source_name,
            source_type="pdf" if ext == ".pdf" else "docx",
            mime_type=_MIME.get(ext, "application/octet-stream"),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            total_pages=total_pages,
            digest=digest,
            extra_metadata={"extraction_mode": "docling"},
        )

        blocks_by_page: dict[int, list] = {}
        for item, _level in document.iterate_items():
            page_no = _page_no(item)
            bucket = blocks_by_page.setdefault(page_no, [])
            label = _label_value(item)
            order = len(bucket)
            document_page_id = build_page_id(str(manifest.revision_id), page_no - 1)

            if label == "table":
                rows = _table_rows(item)
                table = build_table(rows) if rows else None
                if table is not None:
                    bucket.append(_table_block(document_page_id, page_no, order, table))
                    continue
                # Fall back to a paragraph rendering when structure is unavailable.
                fallback = normalize_ocr_text(getattr(item, "text", "") or "")
                if fallback:
                    bucket.append(_text_block(document_page_id, page_no, order, BlockType.PARAGRAPH, fallback))
                continue

            text = normalize_ocr_text(getattr(item, "text", "") or "")
            if not text:
                continue
            block_type = _LABEL_TO_BLOCK.get(label, BlockType.PARAGRAPH)
            bucket.append(_text_block(document_page_id, page_no, order, block_type, text))

        page_numbers = sorted(blocks_by_page) or [1]
        provenance = lightweight_provenance(
            digest=digest, pipeline_name=PARSER_NAME, pipeline_version=PARSER_VERSION,
        )
        pages = []
        for page_index, page_no in enumerate(page_numbers):
            blocks = blocks_by_page.get(page_no, [])
            native_text = normalize_ocr_text("\n\n".join(block.text for block in blocks))
            score = score_text(native_text)
            level = level_for_score(score)
            # Re-key blocks onto the contiguous internal page index.
            pages.append(
                native_page_result(
                    manifest=manifest, page_index=page_index, native_text=native_text,
                    provenance=provenance, blocks=_rekey(blocks, manifest, page_index),
                    processing_status=to_processing_status(level),
                    quality_gate_passed=level.value in {"accepted", "accepted_with_warning"},
                    quality_score=score,
                )
            )
        return ExtractedDocument.build(manifest=manifest, pages=pages, extractor_route=self.route)


def _text_block(page_id: str, page_no: int, order: int, block_type: BlockType, text: str):
    return make_block(
        page_id=page_id, page_number=page_no, block_type=block_type, text=text,
        reading_order=order, source_layer=TextLayer.NATIVE, extraction_route=ExtractionRoute.NATIVE,
    )


def _table_block(page_id: str, page_no: int, order: int, table):
    return make_block(
        page_id=page_id, page_number=page_no, block_type=BlockType.TABLE,
        text=table_reading_text(table), reading_order=order, source_layer=TextLayer.NATIVE,
        extraction_route=ExtractionRoute.NATIVE, table=table,
    )


def _rekey(blocks, manifest, page_index: int) -> list:
    """Rebuild blocks so page_number and block_id match the contiguous page index."""
    page_no = page_index + 1
    page_id = build_page_id(str(manifest.revision_id), page_index)
    rekeyed = []
    for order, block in enumerate(blocks):
        rekeyed.append(
            make_block(
                page_id=page_id, page_number=page_no, block_type=block.block_type,
                text=block.text, reading_order=order, source_layer=block.source_layer,
                extraction_route=block.extraction_route, table=block.table,
                metadata=block.metadata,
            )
        )
    return rekeyed
