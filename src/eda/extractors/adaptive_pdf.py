"""Adaptive OCR PDF extractor: a thin wrapper over the existing engine.

The heavy `eda.adaptive_ocr` module (OpenCV, Tesseract) is imported lazily so the
extractor package stays importable on hosts without those runtime dependencies.
The adaptive engine already emits canonical, quality-gated `PageResult`s, so this
wrapper only re-homes them into an `ExtractedDocument`; it adds no blocks, letting
the chunker use each page's deduplicated ``index_text``.
"""

from __future__ import annotations

from pathlib import Path

from eda.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorRoute,
    ExtractorUnavailable,
)


class AdaptivePdfExtractor(DocumentExtractor):
    route = ExtractorRoute.ADAPTIVE_PDF_OCR
    supported_extensions = frozenset({".pdf"})

    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        # Lazy import: OpenCV/Tesseract are only needed on the OCR route.
        from eda.adaptive_ocr import (
            AdaptiveOCRConfig,
            AdaptivePDFError,
            AdaptivePDFExtractor,
            OCRLanguageUnavailableError,
            OCRUnavailableError,
        )

        config = options.adaptive_config or AdaptiveOCRConfig()
        if not isinstance(config, AdaptiveOCRConfig):
            raise TypeError("adaptive_config must be an AdaptiveOCRConfig instance.")
        try:
            extraction = AdaptivePDFExtractor(config).extract(
                path,
                tenant_id=options.tenant_id,
                logical_document_key=options.logical_document_key,
                source_name=options.source_name,
                page_start=options.page_start,
                page_end=options.page_end,
            )
        except (OCRUnavailableError, OCRLanguageUnavailableError) as error:
            raise ExtractorUnavailable(str(error)) from error
        except AdaptivePDFError as error:
            raise ExtractionFailed(str(error)) from error
        return ExtractedDocument.build(
            manifest=extraction.manifest,
            pages=extraction.pages,
            extractor_route=self.route,
        )
