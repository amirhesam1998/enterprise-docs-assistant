"""Explicit, testable extraction router with an ordered fallback chain.

Routing is deterministic: for a given file the router builds the ordered list of
extractors that declare support, tries them in turn, and returns the first result
that is *sufficient* (produced at least one accepted or needs-review page). An
extractor that is unavailable, fails, or yields only empty/failed pages is skipped
with a recorded warning — a scanned PDF thus falls through the native route to
Docling and finally to adaptive OCR. Nothing is ever silently promoted: the
returned document carries its own quality verdict.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from eda.extractors.adaptive_pdf import AdaptivePdfExtractor
from eda.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorUnavailable,
    extension_of,
)
from eda.extractors.docx import DocxExtractor
from eda.extractors.image import ImageOcrExtractor
from eda.extractors.native_pdf import NativePdfExtractor
from eda.extractors.xlsx import XlsxExtractor


def _sufficient(document: ExtractedDocument) -> bool:
    """Output is sufficient when at least one page is usable or reviewable."""
    return document.quality.accepted_pages > 0 or document.quality.needs_review_pages > 0


class ExtractionRouter:
    def __init__(self, extractors: list[DocumentExtractor]):
        if not extractors:
            raise ValueError("ExtractionRouter requires at least one extractor.")
        self.extractors = list(extractors)

    def candidates(
        self, path: str | Path, mime_type: str | None = None
    ) -> list[DocumentExtractor]:
        ext = extension_of(path)
        return [e for e in self.extractors if e.supports(path, mime_type, ext)]

    def route(self, path: str | Path, mime_type: str | None = None) -> DocumentExtractor:
        candidates = self.candidates(path, mime_type)
        if not candidates:
            raise ExtractionFailed(f"No extractor supports extension {extension_of(path)!r}.")
        return candidates[0]

    def extract(
        self,
        path: str | Path,
        *,
        options: ExtractionOptions,
        mime_type: str | None = None,
    ) -> ExtractedDocument:
        candidates = self.candidates(path, mime_type)
        if not candidates:
            raise ExtractionFailed(f"No extractor supports extension {extension_of(path)!r}.")

        warnings: list[str] = []
        attempts: list[ExtractedDocument] = []
        for extractor in candidates:
            try:
                document = extractor.extract(path, options=options)
            except ExtractorUnavailable:
                warnings.append(f"{extractor.name}_unavailable")
                continue
            except ExtractionFailed:
                warnings.append(f"{extractor.name}_failed")
                continue
            if _sufficient(document):
                return replace(document, warnings=tuple(warnings) + document.warnings)
            warnings.append(f"{extractor.name}_insufficient_output")
            attempts.append(document)

        if attempts:
            best = max(attempts, key=lambda d: (d.quality.accepted_pages, d.quality.score))
            return replace(
                best, warnings=tuple(warnings) + ("all_routes_insufficient",) + best.warnings
            )
        raise ExtractionFailed("No extractor produced usable output for this document.")


def default_router() -> ExtractionRouter:
    """Fast-first policy: native/office parsers lead, Docling and OCR back them up.

    Digital PDFs are served cheaply by the native route; scanned PDFs fall through
    to Docling and then adaptive OCR. Set ``prefer_docling=True`` to lead with the
    richer (heavier) Docling engine for PDFs and DOCX.
    """
    extractors: list[DocumentExtractor] = [NativePdfExtractor()]
    docling = _docling_or_none()
    if docling is not None:
        extractors.append(docling)
    extractors.extend(
        [
            AdaptivePdfExtractor(),
            DocxExtractor(),
            XlsxExtractor(),
            ImageOcrExtractor(),
        ]
    )
    return ExtractionRouter(extractors)


def docling_first_router() -> ExtractionRouter:
    """Prefer Docling for PDFs and DOCX, keeping native/OCR routes as fallback."""
    extractors: list[DocumentExtractor] = []
    docling = _docling_or_none()
    if docling is not None:
        extractors.append(docling)
    extractors.extend(
        [
            NativePdfExtractor(),
            AdaptivePdfExtractor(),
            DocxExtractor(),
            XlsxExtractor(),
            ImageOcrExtractor(),
        ]
    )
    return ExtractionRouter(extractors)


def _docling_or_none() -> DocumentExtractor | None:
    from eda.extractors.docling_extractor import DoclingExtractor, docling_available

    return DoclingExtractor() if docling_available() else None
