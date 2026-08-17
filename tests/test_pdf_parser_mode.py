from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image

import eda.adaptive_ocr as adaptive
import eda.parse as parse
from eda.adaptive_ocr import (
    AdaptiveOCRConfig,
    AdaptivePDFExtractor,
    CandidateBatch,
    CandidatePlan,
    InvalidPageRangeError,
    OCRLanguageUnavailableError,
    OCRTimeoutError,
    UnreadablePDFError,
)
from eda.ingestion_schema import ExtractionRoute


def test_native_mode_is_default_and_does_not_construct_adaptive_extractor(monkeypatch):
    sentinel = [object()]
    monkeypatch.delenv("EDA_PDF_EXTRACTION_MODE", raising=False)
    monkeypatch.setattr(parse, "_parse_pdf_native", lambda *args, **kwargs: sentinel)
    monkeypatch.setattr(parse, "AdaptivePDFExtractor", lambda *args, **kwargs: pytest.fail("adaptive used"))
    assert parse.parse_pdf("unused.pdf", "tenant", "source.pdf") is sentinel


def test_explicit_adaptive_mode_uses_typed_pipeline(monkeypatch):
    extraction = SimpleNamespace(manifest=object(), pages=(object(),))

    class FakeExtractor:
        def __init__(self, config):
            assert isinstance(config, AdaptiveOCRConfig)

        def extract(self, *args, **kwargs):
            assert kwargs["logical_document_key"] == "upload-object-id"
            return extraction

    monkeypatch.setattr(parse, "AdaptivePDFExtractor", FakeExtractor)
    monkeypatch.setattr(parse, "extraction_to_chunks", lambda pages, manifest, **kwargs: ["typed-chunk"])
    assert parse.parse_pdf(
        "unused.pdf",
        "tenant",
        "source.pdf",
        acl_groups=["finance"],
        extraction_mode="adaptive",
        logical_document_key="upload-object-id",
    ) == ["typed-chunk"]


def test_invalid_mode_and_missing_logical_key_fail_clearly():
    with pytest.raises(ValueError, match="native.*adaptive"):
        parse.resolve_pdf_extraction_mode("automatic")
    with pytest.raises(ValueError, match="logical_document_key"):
        parse.parse_pdf("unused.pdf", "tenant", "source.pdf", extraction_mode="adaptive")


def test_missing_requested_language_pack_is_clear(monkeypatch):
    monkeypatch.setattr(adaptive.pytesseract, "get_languages", lambda config="": ["eng"])
    with pytest.raises(OCRLanguageUnavailableError, match="fas"):
        adaptive._validate_tesseract(AdaptiveOCRConfig(language_profiles=("fas",)))


def test_ocr_timeout_is_converted_to_domain_error(monkeypatch):
    monkeypatch.setattr(
        adaptive.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")),
    )
    plan = CandidatePlan(ExtractionRoute.FULL_PAGE_OCR, 6, "eng", "original")
    with pytest.raises(OCRTimeoutError, match="timed out"):
        adaptive._ocr_data(Image.new("RGB", (10, 10), "white"), plan, timeout=1)


def test_unreadable_pdf_and_invalid_page_range_are_clear(tmp_path):
    extractor = AdaptivePDFExtractor(candidate_provider=lambda *args: CandidateBatch(()))
    with pytest.raises(UnreadablePDFError, match="unreadable"):
        extractor.extract(
            tmp_path / "missing.pdf",
            tenant_id="tenant",
            logical_document_key="document",
            source_name="missing.pdf",
        )

    path = tmp_path / "one-page.pdf"
    document = pymupdf.open()
    document.new_page()
    document.save(path)
    document.close()
    with pytest.raises(InvalidPageRangeError, match="range"):
        extractor.extract(
            path,
            tenant_id="tenant",
            logical_document_key="document",
            source_name="one-page.pdf",
            page_start=1,
        )
