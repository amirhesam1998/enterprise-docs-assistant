"""Celery ingestion pipeline selection: legacy vs. canonical vs. docling_first.

These are pure unit tests: parse_any, ingest_chunks, extract_document_chunks, the
routers, and QdrantClient are all patched, so no PDF/Tesseract/Docling/Qdrant/
Redis/Ollama runtime is required and no network calls happen.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api import config, tasks
from api.tasks import IngestionError, _resolve_pipeline, ingest_document


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeChunk:
    def __init__(self, chunk_id: str = "page-0"):
        self.text = "some content"
        self.tenant_id = None
        self.acl_groups: list[str] = []
        self.chunk_id = chunk_id


def fake_document(
    *,
    level: str = "accepted",
    accepted: int = 1,
    needs_review: int = 0,
    failed: int = 0,
    empty: int = 0,
    warnings: tuple[str, ...] = (),
    route: str = "native_pdf",
    tables: int = 0,
    score: float = 95.0,
):
    quality = SimpleNamespace(
        score=score,
        level=SimpleNamespace(value=level),
        total_pages=accepted + needs_review + failed + empty,
        accepted_pages=accepted,
        needs_review_pages=needs_review,
        failed_pages=failed,
        empty_pages=empty,
        warnings=list(warnings),
    )
    return SimpleNamespace(
        extractor_route=SimpleNamespace(value=route),
        quality=quality,
        warnings=(),
        errors=(),
        table_count=tables,
    )


@pytest.fixture
def patched(monkeypatch):
    """Patch the worker's collaborators and capture what reaches the vector index."""
    captured: dict = {}

    def fake_ingest_chunks(chunks, client, collection):
        captured["chunks"] = list(chunks)
        captured["collection"] = collection
        return len(chunks)

    monkeypatch.setattr(tasks, "QdrantClient", lambda url=None: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(tasks, "ingest_chunks", fake_ingest_chunks)
    monkeypatch.setattr(tasks, "default_router", lambda: "DEFAULT_ROUTER")
    monkeypatch.setattr(tasks, "docling_first_router", lambda: "DOCLING_ROUTER")
    monkeypatch.setattr(config, "INGESTION_ALLOW_NEEDS_REVIEW", False)
    monkeypatch.setattr(config, "INGESTION_FAIL_ON_ZERO_CHUNKS", True)
    monkeypatch.setattr(config, "INGESTION_MAX_CHUNK_WORDS", 350)
    return captured


def _run(**kwargs):
    """Run the task synchronously; return the EagerResult without re-raising."""
    return ingest_document.apply(
        kwargs={
            "path": kwargs.get("path", "data/uploads/x.pdf"),
            "tenant_id": kwargs.get("tenant_id", "kb"),
            "source": kwargs.get("source", "report.pdf"),
            "acl_groups": kwargs.get("acl_groups", ["billing"]),
        },
        throw=False,
    )


# --------------------------------------------------------------------------- #
# Pipeline resolution
# --------------------------------------------------------------------------- #
def test_resolve_pipeline_accepts_known_values(monkeypatch):
    for value in ("legacy", "canonical", "docling_first"):
        monkeypatch.setattr(config, "INGESTION_PIPELINE", value)
        assert _resolve_pipeline() == value


def test_invalid_pipeline_fails_clearly(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "bogus")
    with pytest.raises(ValueError, match="INGESTION_PIPELINE"):
        _resolve_pipeline()
    result = _run()
    assert result.status == "FAILURE"
    assert isinstance(result.result, ValueError)


# --------------------------------------------------------------------------- #
# Legacy mode
# --------------------------------------------------------------------------- #
def test_legacy_mode_uses_parse_any_and_ingest_chunks(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "legacy")
    called = {}

    def fake_parse_any(path, tenant_id, source, acl_groups=None, **kw):
        called["parse_any"] = True
        return [FakeChunk("legacy-0"), FakeChunk("legacy-1")]

    monkeypatch.setattr(tasks, "parse_any", fake_parse_any)

    result = _run()
    assert result.successful()
    # Legacy result shape is preserved exactly — no canonical keys added.
    assert result.result == {"chunks": 2, "source": "report.pdf", "tenant_id": "kb"}
    assert called.get("parse_any")
    assert len(patched["chunks"]) == 2


# --------------------------------------------------------------------------- #
# Canonical mode
# --------------------------------------------------------------------------- #
def test_canonical_mode_extracts_then_ingests(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    calls = {}

    def fake_extract(path, **kwargs):
        calls["kwargs"] = kwargs
        return fake_document(), [FakeChunk("p0"), FakeChunk("p1")]

    monkeypatch.setattr(tasks, "extract_document_chunks", fake_extract)

    result = _run()
    assert result.successful()
    payload = result.result
    assert payload["ingestion_pipeline"] == "canonical"
    assert payload["ingestion_status"] == "indexed"
    assert payload["embedded_chunks"] == 2
    assert payload["chunks"] == 2
    # canonical mode uses the default router.
    assert calls["kwargs"]["router"] == "DEFAULT_ROUTER"
    assert len(patched["chunks"]) == 2


def test_canonical_result_carries_quality_metadata(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    document = fake_document(
        level="accepted_with_warning", warnings=("native_pdf_insufficient_output",),
        route="docling", tables=3, score=82.0,
    )
    monkeypatch.setattr(
        tasks, "extract_document_chunks", lambda path, **kw: (document, [FakeChunk("p0")])
    )

    payload = _run().result
    assert payload["ingestion_status"] == "indexed_with_warnings"
    assert payload["quality_score"] == 82.0
    assert payload["quality_level"] == "accepted_with_warning"
    assert payload["extraction_route"] == "docling"
    assert payload["table_count"] == 3
    assert "native_pdf_insufficient_output" in payload["warnings"]
    assert payload["total_pages"] == 1 and payload["accepted_pages"] == 1


def test_canonical_preserves_tenant_and_acl_on_chunks(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    monkeypatch.setattr(
        tasks, "extract_document_chunks",
        lambda path, **kw: (fake_document(), [FakeChunk("p0"), FakeChunk("p1")]),
    )

    _run(tenant_id="kb", acl_groups=["billing"])
    for chunk in patched["chunks"]:
        assert chunk.tenant_id == "kb"
        assert chunk.acl_groups == ["billing"]
        assert chunk.chunk_id.startswith("kb:")


def test_docling_first_mode_uses_docling_router(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "docling_first")
    calls = {}

    def fake_extract(path, **kwargs):
        calls["router"] = kwargs["router"]
        return fake_document(route="docling"), [FakeChunk("p0")]

    monkeypatch.setattr(tasks, "extract_document_chunks", fake_extract)

    result = _run()
    assert result.successful()
    assert calls["router"] == "DOCLING_ROUTER"
    assert result.result["ingestion_pipeline"] == "docling_first"


# --------------------------------------------------------------------------- #
# Quality gating: zero embeddable chunks
# --------------------------------------------------------------------------- #
def test_needs_review_is_a_business_result_not_a_crash(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    document = fake_document(level="needs_review", accepted=0, needs_review=2, score=55.0)
    monkeypatch.setattr(tasks, "extract_document_chunks", lambda path, **kw: (document, []))

    result = _run()
    assert result.successful()  # SUCCESS, not FAILURE
    assert result.result["ingestion_status"] == "needs_review"
    assert result.result["embedded_chunks"] == 0
    assert "chunks" not in patched  # ingest_chunks was never called; nothing upserted


def test_all_failed_extraction_fails_loudly_by_default(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    document = fake_document(level="failed", accepted=0, failed=1, empty=0, score=10.0)
    monkeypatch.setattr(tasks, "extract_document_chunks", lambda path, **kw: (document, []))

    result = _run()
    assert result.status == "FAILURE"
    assert isinstance(result.result, IngestionError)
    assert "chunks" not in patched  # nothing upserted


def test_all_failed_extraction_can_be_soft_when_flag_disabled(monkeypatch, patched):
    monkeypatch.setattr(config, "INGESTION_PIPELINE", "canonical")
    monkeypatch.setattr(config, "INGESTION_FAIL_ON_ZERO_CHUNKS", False)
    document = fake_document(level="failed", accepted=0, failed=1, score=10.0)
    monkeypatch.setattr(tasks, "extract_document_chunks", lambda path, **kw: (document, []))

    result = _run()
    assert result.successful()
    assert result.result["ingestion_status"] == "failed"
    assert result.result["embedded_chunks"] == 0
    assert "chunks" not in patched


# --------------------------------------------------------------------------- #
# XLSX ACL requirement remains intact at the extractor boundary
# --------------------------------------------------------------------------- #
def test_xlsx_extractor_still_requires_acl(tmp_path):
    import openpyxl

    from eda.extractors.base import ExtractionOptions
    from eda.extractors.xlsx import XlsxExtractor

    workbook = openpyxl.Workbook()
    workbook.active.append(["Category", "Amount"])
    path = tmp_path / "budget.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="ACL"):
        XlsxExtractor().extract(
            path,
            options=ExtractionOptions(
                tenant_id="kb", logical_document_key="budget.xlsx",
                source_name="budget.xlsx", acl_groups=(),
            ),
        )
