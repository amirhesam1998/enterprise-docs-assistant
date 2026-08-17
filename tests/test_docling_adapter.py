from __future__ import annotations

import pytest

# The adapter module must import whether or not the Docling engine is installed.
from eda.extractors.docling_extractor import DoclingExtractor, docling_available
from eda.extractors.base import ExtractionOptions, ExtractorUnavailable


def test_docling_extractor_advertises_supported_types():
    extractor = DoclingExtractor()
    assert extractor.supports("report.pdf")
    assert extractor.supports("report.docx")
    assert not extractor.supports("image.png")
    assert not extractor.supports("sheet.xlsx")


def test_docling_available_returns_bool():
    assert isinstance(docling_available(), bool)


@pytest.mark.skipif(docling_available(), reason="Docling is installed in this environment.")
def test_extract_raises_cleanly_when_docling_missing(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    options = ExtractionOptions(
        tenant_id="kb", logical_document_key="doc.pdf", source_name="doc.pdf"
    )
    with pytest.raises(ExtractorUnavailable):
        DoclingExtractor().extract(path, options=options)
