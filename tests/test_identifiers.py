from eda.identifiers import (
    chunk_id,
    document_id,
    page_id,
    region_id,
    revision_id,
    sha256_file,
)


def test_file_hash_is_stable(tmp_path):
    source = tmp_path / "fixture.bin"
    source.write_bytes(b"synthetic fixture")
    assert sha256_file(source) == sha256_file(source)
    assert len(sha256_file(source)) == 64


def test_document_id_is_stable_and_tenant_scoped():
    first = document_id("tenant-a", "dms:policy-42")
    assert first == document_id(" TENANT-A ", "DMS:POLICY-42")
    assert first != document_id("tenant-b", "dms:policy-42")


def test_content_changes_revision_id():
    document = document_id("tenant-a", "dms:policy-42")
    assert revision_id(document, "a" * 64) != revision_id(document, "b" * 64)


def test_page_region_and_chunk_ids_use_deterministic_order():
    revision = revision_id(document_id("tenant-a", "dms:policy-42"), "a" * 64)
    first_page = page_id(revision, 0)
    second_page = page_id(revision, 1)
    assert first_page != second_page
    assert region_id(first_page, "ocr", "region_ocr", 0) == region_id(
        first_page, "OCR", "REGION_OCR", 0
    )
    assert region_id(first_page, "ocr", "region_ocr", 0) != region_id(
        first_page, "native", "native", 0
    )
    assert chunk_id(first_page, 0) == chunk_id(first_page, 0)
    assert chunk_id(first_page, 0) != chunk_id(first_page, 1)
