"""DOCX extractor: order-preserving paragraphs, headings, lists, and tables.

Word has no fixed pagination, so the document is modeled as a single canonical
page (page_number=1) whose blocks preserve body order by walking the XML body
rather than the separate paragraphs/tables collections (which lose interleaving).
"""

from __future__ import annotations

from pathlib import Path

import docx
from docx.document import Document as _Document
from docx.table import Table
from docx.text.paragraph import Paragraph

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
)

PARSER_NAME = "docx"
PARSER_VERSION = "1.0"


def _iter_body(document: _Document):
    """Yield Paragraph/Table objects in true body order."""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _paragraph_block_type(paragraph: Paragraph) -> BlockType | None:
    text = normalize_ocr_text(paragraph.text)
    if not text:
        return None
    style = (paragraph.style.name if paragraph.style else "") or ""
    lowered = style.lower()
    if lowered.startswith("heading") or lowered in {"title", "subtitle"}:
        return BlockType.HEADING
    if "list" in lowered:
        return BlockType.LIST_ITEM
    return BlockType.PARAGRAPH


class DocxExtractor(DocumentExtractor):
    route = ExtractorRoute.DOCX
    supported_extensions = frozenset({".docx"})

    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        source = Path(path)
        if not source.is_file():
            raise ExtractionFailed("DOCX source is unavailable or unreadable.")
        digest = sha256_file(source)
        try:
            document = docx.Document(str(source))
        except Exception as error:  # noqa: BLE001 - message intentionally path-free
            raise ExtractionFailed("DOCX source could not be opened.") from error

        manifest = build_manifest(
            path=source,
            tenant_id=options.tenant_id,
            logical_document_key=options.logical_document_key,
            source_name=options.source_name,
            source_type="docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            total_pages=1,
            digest=digest,
        )
        page_id = build_page_id(str(manifest.revision_id), 0)

        blocks = []
        order = 0
        for item in _iter_body(document):
            if isinstance(item, Paragraph):
                block_type = _paragraph_block_type(item)
                if block_type is None:
                    continue
                blocks.append(
                    make_block(
                        page_id=page_id, page_number=1, block_type=block_type,
                        text=normalize_ocr_text(item.text), reading_order=order,
                        source_layer=TextLayer.NATIVE, extraction_route=ExtractionRoute.NATIVE,
                    )
                )
                order += 1
            elif isinstance(item, Table):
                rows = [[cell.text for cell in row.cells] for row in item.rows]
                table = build_table(rows)
                if table is None:
                    continue
                blocks.append(
                    make_block(
                        page_id=page_id, page_number=1, block_type=BlockType.TABLE,
                        text=table_reading_text(table), reading_order=order,
                        source_layer=TextLayer.NATIVE, extraction_route=ExtractionRoute.NATIVE,
                        table=table,
                    )
                )
                order += 1

        native_text = normalize_ocr_text("\n\n".join(block.text for block in blocks))
        score = score_text(native_text)
        level = level_for_score(score)
        page = native_page_result(
            manifest=manifest, page_index=0, native_text=native_text,
            provenance=lightweight_provenance(
                digest=digest, pipeline_name=PARSER_NAME, pipeline_version=PARSER_VERSION,
            ),
            blocks=blocks, processing_status=to_processing_status(level),
            quality_gate_passed=level.value in {"accepted", "accepted_with_warning"},
            quality_score=score,
        )
        return ExtractedDocument.build(manifest=manifest, pages=[page], extractor_route=self.route)
