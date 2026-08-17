"""Image OCR extractor: a single scanned page via Tesseract (fas+eng).

A lightweight wrapper over the legacy image path, producing canonical scanned
output. Requires Tesseract; if unavailable it raises ExtractorUnavailable so the
router can record the gap rather than silently emitting nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytesseract
from PIL import Image

from eda.canonical import (
    build_manifest,
    lightweight_provenance,
    make_block,
    ocr_page_result,
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

PARSER_NAME = "image_ocr"
PARSER_VERSION = "1.0"

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


class ImageOcrExtractor(DocumentExtractor):
    route = ExtractorRoute.IMAGE_OCR
    supported_extensions = frozenset({".png", ".jpg", ".jpeg"})

    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        source = Path(path)
        if not source.is_file():
            raise ExtractionFailed("Image source is unavailable or unreadable.")
        command = os.getenv("TESSERACT_CMD")
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        digest = sha256_file(source)
        try:
            with Image.open(source) as handle:
                image = handle.convert("RGB")
            ocr_text = normalize_ocr_text(
                pytesseract.image_to_string(image, lang=options.ocr_languages)
            )
        except pytesseract.TesseractNotFoundError as error:
            raise ExtractorUnavailable("Tesseract is unavailable for image OCR.") from error
        except Exception as error:  # noqa: BLE001 - message intentionally path-free
            raise ExtractionFailed("Image OCR failed to produce output.") from error

        ext = os.path.splitext(str(source))[1].lower()
        manifest = build_manifest(
            path=source,
            tenant_id=options.tenant_id,
            logical_document_key=options.logical_document_key,
            source_name=options.source_name,
            source_type="image",
            mime_type=_MIME.get(ext, "application/octet-stream"),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            total_pages=1,
            digest=digest,
        )
        page_id = build_page_id(str(manifest.revision_id), 0)
        blocks = []
        if ocr_text.strip():
            blocks.append(
                make_block(
                    page_id=page_id, page_number=1, block_type=BlockType.IMAGE_TEXT,
                    text=ocr_text, reading_order=0, source_layer=TextLayer.OCR,
                    extraction_route=ExtractionRoute.FULL_PAGE_OCR,
                    language_profile=options.ocr_languages,
                )
            )
        score = score_text(ocr_text)
        level = level_for_score(score)
        page = ocr_page_result(
            manifest=manifest, page_index=0, ocr_text=ocr_text,
            provenance=lightweight_provenance(
                digest=digest, pipeline_name=PARSER_NAME, pipeline_version=PARSER_VERSION,
                resolved_language_profiles=[options.ocr_languages],
            ),
            blocks=blocks, processing_status=to_processing_status(level),
            quality_gate_passed=level.value in {"accepted", "accepted_with_warning"},
            quality_score=score, language_profile=options.ocr_languages,
        )
        return ExtractedDocument.build(manifest=manifest, pages=[page], extractor_route=self.route)
