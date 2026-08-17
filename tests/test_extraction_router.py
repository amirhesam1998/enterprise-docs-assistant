from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eda.extractors import default_router
from eda.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorRoute,
    ExtractorUnavailable,
)
from eda.extractors.router import ExtractionRouter
from eda.ingestion_schema import (
    DocumentManifest,
    ExtractionRoute as PageRoute,
    OCRDecision,
    PageType,
    ProcessingStatus,
)


def _manifest(identity) -> DocumentManifest:
    return DocumentManifest(
        document_id=identity["document_id"],
        revision_id=identity["revision_id"],
        tenant_id="tenant-a",
        source_name="doc.pdf",
        source_type="pdf",
        source_sha256=identity["digest"],
        file_size_bytes=10,
        mime_type="application/pdf",
        total_pages=1,
        parser_name="fake",
        parser_version="1.0",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _accepted_doc(identity, page_factory, route) -> ExtractedDocument:
    return ExtractedDocument.build(
        manifest=_manifest(identity), pages=[page_factory()], extractor_route=route,
    )


def _failed_doc(identity, page_factory, route) -> ExtractedDocument:
    page = page_factory(
        native_text="",
        processing_status=ProcessingStatus.FAILED,
        page_type=PageType.EMPTY,
        ocr_decision=OCRDecision(
            selected_route=PageRoute.REJECTED, quality_gate_passed=False, candidate_count=0
        ),
    )
    return ExtractedDocument.build(
        manifest=_manifest(identity), pages=[page], extractor_route=route,
    )


class FakeExtractor(DocumentExtractor):
    def __init__(self, route, extensions, *, document=None, error=None):
        self.route = route
        self.supported_extensions = frozenset(extensions)
        self._document = document
        self._error = error

    def extract(self, path, *, options):
        if self._error is not None:
            raise self._error
        return self._document


OPTIONS = ExtractionOptions(tenant_id="t", logical_document_key="k", source_name="doc.pdf")


# --- default router wiring ------------------------------------------------

def test_default_router_pdf_candidate_order():
    names = [e.name for e in default_router().candidates("file.pdf")]
    assert names[0] == "native_pdf"
    assert "adaptive_pdf_ocr" in names


def test_default_router_selects_by_extension():
    router = default_router()
    assert router.route("a.xlsx").name == "xlsx"
    assert router.route("a.png").name == "image_ocr"
    assert router.route("a.docx").name in {"docling", "docx"}


def test_router_rejects_unsupported_extension():
    with pytest.raises(ExtractionFailed):
        default_router().route("a.zip")


# --- fallback behavior ----------------------------------------------------

def test_router_falls_back_when_primary_insufficient(identity, page_factory):
    primary = FakeExtractor(
        ExtractorRoute.NATIVE_PDF, {".pdf"},
        document=_failed_doc(identity, page_factory, ExtractorRoute.NATIVE_PDF),
    )
    backup = FakeExtractor(
        ExtractorRoute.DOCLING, {".pdf"},
        document=_accepted_doc(identity, page_factory, ExtractorRoute.DOCLING),
    )
    router = ExtractionRouter([primary, backup])
    result = router.extract("x.pdf", options=OPTIONS)
    assert result.extractor_route == ExtractorRoute.DOCLING
    assert "native_pdf_insufficient_output" in result.warnings


def test_router_skips_unavailable_extractor(identity, page_factory):
    primary = FakeExtractor(
        ExtractorRoute.DOCLING, {".pdf"}, error=ExtractorUnavailable("no engine")
    )
    backup = FakeExtractor(
        ExtractorRoute.NATIVE_PDF, {".pdf"},
        document=_accepted_doc(identity, page_factory, ExtractorRoute.NATIVE_PDF),
    )
    router = ExtractionRouter([primary, backup])
    result = router.extract("x.pdf", options=OPTIONS)
    assert result.extractor_route == ExtractorRoute.NATIVE_PDF
    assert "docling_unavailable" in result.warnings


def test_router_returns_best_effort_when_all_insufficient(identity, page_factory):
    primary = FakeExtractor(
        ExtractorRoute.NATIVE_PDF, {".pdf"},
        document=_failed_doc(identity, page_factory, ExtractorRoute.NATIVE_PDF),
    )
    router = ExtractionRouter([primary])
    result = router.extract("x.pdf", options=OPTIONS)
    assert "all_routes_insufficient" in result.warnings
    assert result.quality.accepted_pages == 0


def test_router_raises_when_every_route_errors():
    primary = FakeExtractor(ExtractorRoute.NATIVE_PDF, {".pdf"}, error=ExtractionFailed("boom"))
    router = ExtractionRouter([primary])
    with pytest.raises(ExtractionFailed):
        router.extract("x.pdf", options=OPTIONS)
