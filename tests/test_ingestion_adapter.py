from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eda.identifiers import revision_id
from eda.ingestion_adapter import page_result_to_chunk
from eda.ingestion_schema import (
    DocumentManifest,
    ExtractionRoute,
    OCRDecision,
    ProcessingStatus,
)


def manifest(identity):
    return DocumentManifest(
        document_id=identity["document_id"],
        revision_id=identity["revision_id"],
        tenant_id="tenant-a",
        source_name="policy.pdf",
        source_type="pdf",
        source_sha256=identity["digest"],
        file_size_bytes=100,
        mime_type="application/pdf",
        total_pages=1,
        parser_name="adaptive_pdf_ocr",
        parser_version="1.0",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_adapter_preserves_tenant_acl_ids_and_one_based_citation(identity, page_factory):
    chunk = page_result_to_chunk(page_factory(), manifest(identity), acl_groups=["finance", "finance"])
    assert chunk.tenant_id == "tenant-a"
    assert chunk.acl_groups == ["finance"]
    assert chunk.location["num"] == 1
    assert chunk.location["page_id"] == identity["page_id"]
    assert chunk.location["document_id"] == identity["document_id"]
    assert chunk.location["revision_id"] == identity["revision_id"]
    assert chunk.chunk_id


def test_adapter_rejects_missing_acl(identity, page_factory):
    with pytest.raises(ValueError, match="ACL"):
        page_result_to_chunk(page_factory(), manifest(identity), acl_groups=[])


def test_adapter_rejects_needs_review_by_default(identity, page_factory):
    page = page_factory(
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.NATIVE,
            quality_gate_passed=False,
            candidate_count=1,
        ),
    )
    with pytest.raises(ValueError, match="needs_review"):
        page_result_to_chunk(page, manifest(identity), acl_groups=["finance"])
    assert page_result_to_chunk(
        page,
        manifest(identity),
        acl_groups=["finance"],
        allow_needs_review=True,
    ).text


def test_adapter_rejects_failed_or_mismatched_page(identity, provenance, page_factory):
    failed = page_factory(
        native_text="",
        processing_status=ProcessingStatus.FAILED,
        ocr_decision=OCRDecision(
            selected_route=ExtractionRoute.REJECTED,
            quality_gate_passed=False,
            candidate_count=0,
        ),
    )
    with pytest.raises(ValueError, match="Failed"):
        page_result_to_chunk(failed, manifest(identity), acl_groups=["finance"])

