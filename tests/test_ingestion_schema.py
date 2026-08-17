from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from eda.evaluation_schema import EvaluationManifest
from eda.ingestion_schema import (
    DocumentManifest,
    ExtractionRoute,
    OCRDecision,
    ProcessingProvenance,
    TextLayer,
    TextRegion,
)
from eda.identifiers import document_id, region_id, revision_id


def make_manifest(**overrides) -> DocumentManifest:
    digest = "a" * 64
    document = document_id("tenant-a", "dms:policy-42")
    values = {
        "document_id": document,
        "revision_id": revision_id(document, digest),
        "tenant_id": "tenant-a",
        "source_name": "policy.pdf",
        "source_type": "pdf",
        "source_sha256": digest,
        "file_size_bytes": 42,
        "mime_type": "application/pdf",
        "total_pages": 1,
        "parser_name": "synthetic",
        "parser_version": "1.0",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "metadata": {"department": "policy"},
    }
    values.update(overrides)
    return DocumentManifest(**values)


def test_manifest_json_round_trip():
    manifest = make_manifest()
    assert DocumentManifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_manifest_rejects_revision_that_does_not_match_content():
    with pytest.raises(ValidationError):
        make_manifest(revision_id="00000000-0000-0000-0000-000000000000")


@pytest.mark.parametrize(
    "override",
    [
        {"source_sha256": "not-a-hash"},
        {"file_size_bytes": -1},
        {"total_pages": 0},
        {"source_name": r"C:\private\policy.pdf"},
        {"metadata": {"password": "redacted"}},
        {"metadata": {"source": "/private/policy.pdf"}},
        {"metadata": {"text": "must not be duplicated"}},
    ],
)
def test_manifest_rejects_invalid_or_private_fields(override):
    with pytest.raises((ValidationError, ValueError)):
        make_manifest(**override)


def test_region_validates_coordinate_convention(identity):
    item = TextRegion(
        region_id=region_id(identity["page_id"], "ocr", "region_ocr", 0),
        source_layer=TextLayer.OCR,
        text="synthetic",
        bbox=(1, 2, 10, 20),
        reading_order=0,
        confidence=75,
    )
    assert item.bbox == (1, 2, 10, 20)
    with pytest.raises(ValidationError):
        TextRegion(**{**item.model_dump(), "bbox": (10, 2, 1, 20)})


def test_provenance_json_round_trip(provenance):
    encoded = provenance.model_dump_json()
    assert ProcessingProvenance.model_validate_json(encoded) == provenance
    assert "C:\\" not in encoded and "password" not in encoded.casefold()


@pytest.mark.parametrize(
    "message",
    [r"failed at C:\private\document.pdf", "password=redacted"],
)
def test_public_decision_messages_reject_paths_and_secret_values(message):
    with pytest.raises(ValidationError):
        OCRDecision(
            selected_route=ExtractionRoute.REJECTED,
            quality_gate_passed=False,
            candidate_count=0,
            errors=[message],
        )


def test_evaluation_example_matches_typed_schema():
    raw = Path("evaluation/ocr/manifest.example.json").read_text(encoding="utf-8")
    manifest = EvaluationManifest.model_validate_json(raw)
    assert {item.tier.value for item in manifest.fixtures} == {
        "committed_sanitized",
        "local_private",
    }
