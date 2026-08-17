"""Native (digital) PDF extractor built on PyMuPDF text blocks.

Fast, no rendering, no OCR. It preserves PyMuPDF's block reading order and makes
a light heading/list/paragraph classification so the structure-aware chunker has
real blocks to work with. Scanned pages (no extractable text) come out as empty/
failed, which is the router's signal to fall back to adaptive OCR.
"""

from __future__ import annotations

import re
from pathlib import Path
from statistics import median

import pymupdf

from eda.canonical import (
    build_manifest,
    lightweight_provenance,
    make_block,
    native_page_result,
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

PARSER_NAME = "native_pdf"
PARSER_VERSION = "1.0"

_BULLET = re.compile(r"^\s*(?:[•·◦▪–\-\*]|[0-9۰-۹]+[.)]|[a-zA-Z][.)])\s+")


def _classify(text: str, size: float, median_size: float) -> BlockType:
    stripped = text.strip()
    if _BULLET.match(stripped):
        return BlockType.LIST_ITEM
    word_count = len(stripped.split())
    if word_count <= 8 and median_size > 0 and size >= median_size * 1.2 and not stripped.endswith((".", "؟", "?", "!")):
        return BlockType.HEADING
    return BlockType.PARAGRAPH


def _page_blocks(page: pymupdf.Page, page_id: str, page_number: int) -> list:
    data = page.get_text("dict")
    raw_blocks = [block for block in data.get("blocks", []) if block.get("type", 0) == 0]
    sizes: list[float] = [
        span.get("size", 0.0)
        for block in raw_blocks
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("text", "").strip()
    ]
    median_size = median(sizes) if sizes else 0.0

    blocks = []
    order = 0
    for raw in raw_blocks:
        lines = []
        block_sizes: list[float] = []
        for line in raw.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            lines.append("".join(span["text"] for span in spans))
            block_sizes.extend(span.get("size", 0.0) for span in spans)
        text = normalize_ocr_text("\n".join(lines))
        if not text:
            continue
        block_size = max(block_sizes) if block_sizes else 0.0
        bbox = tuple(float(value) for value in raw.get("bbox", (0, 0, 0, 0)))
        safe_bbox = bbox if bbox[2] > bbox[0] and bbox[3] > bbox[1] and bbox[0] >= 0 and bbox[1] >= 0 else None
        blocks.append(
            make_block(
                page_id=page_id,
                page_number=page_number,
                block_type=_classify(text, block_size, median_size),
                text=text,
                reading_order=order,
                source_layer=TextLayer.NATIVE,
                extraction_route=ExtractionRoute.NATIVE,
                bbox=safe_bbox,
            )
        )
        order += 1
    return blocks


class NativePdfExtractor(DocumentExtractor):
    route = ExtractorRoute.NATIVE_PDF
    supported_extensions = frozenset({".pdf"})

    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        source = Path(path)
        if not source.is_file():
            raise ExtractionFailed("PDF source is unavailable or unreadable.")
        digest = sha256_file(source)
        try:
            document = pymupdf.open(source)
        except Exception as error:  # noqa: BLE001 - message intentionally path-free
            raise ExtractionFailed("PDF source could not be opened.") from error
        try:
            if document.needs_pass:
                raise ExtractionFailed("Encrypted PDFs are not supported by the native extractor.")
            total_pages = document.page_count
            end = total_pages if options.page_end is None else min(options.page_end, total_pages)
            manifest = build_manifest(
                path=source,
                tenant_id=options.tenant_id,
                logical_document_key=options.logical_document_key,
                source_name=options.source_name,
                source_type="pdf",
                mime_type="application/pdf",
                parser_name=PARSER_NAME,
                parser_version=PARSER_VERSION,
                total_pages=total_pages,
                digest=digest,
                extra_metadata={"extraction_mode": "native"},
            )
            provenance = lightweight_provenance(
                digest=digest, pipeline_name=PARSER_NAME, pipeline_version=PARSER_VERSION,
            )
            pages = []
            for page_index in range(options.page_start, end):
                page = document.load_page(page_index)
                native_text = normalize_ocr_text(page.get_text("text"))
                page_id = build_page_id(str(manifest.revision_id), page_index)
                blocks = _page_blocks(page, page_id, page_index + 1)
                score = score_text(native_text)
                level = level_for_score(score)
                pages.append(
                    native_page_result(
                        manifest=manifest,
                        page_index=page_index,
                        native_text=native_text,
                        provenance=provenance,
                        blocks=blocks,
                        processing_status=to_processing_status(level),
                        quality_gate_passed=level.value in {"accepted", "accepted_with_warning"},
                        quality_score=score,
                    )
                )
            return ExtractedDocument.build(
                manifest=manifest, pages=pages, extractor_route=self.route,
            )
        finally:
            document.close()
