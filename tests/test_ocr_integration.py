from __future__ import annotations

import os
from pathlib import Path

import pytest

from eda.adaptive_ocr import AdaptiveOCRConfig, AdaptivePDFExtractor


@pytest.mark.ocr_integration
def test_local_private_route_diagnostic():
    if os.getenv("EDA_RUN_OCR_INTEGRATION") != "1":
        pytest.skip("set EDA_RUN_OCR_INTEGRATION=1 for local Tesseract diagnostics")
    path = os.getenv("EDA_PRIVATE_OCR_PDF")
    if not path or not Path(path).is_file():
        pytest.skip("EDA_PRIVATE_OCR_PDF does not identify an approved local fixture")
    result = AdaptivePDFExtractor(AdaptiveOCRConfig()).extract(
        path,
        tenant_id="local-diagnostic",
        logical_document_key="approved-private-diagnostic",
        source_name=Path(path).name,
        page_indexes=(3, 11),
    )
    assert [page.page_number for page in result.pages] == [4, 12]
