from __future__ import annotations

import pytest

from eda.identifiers import block_id as build_block_id
from eda.ingestion_schema import (
    BlockResult,
    BlockType,
    ExtractionRoute,
    TableCell,
    TableResult,
    TextLayer,
)


def _block(identity, **overrides) -> BlockResult:
    values = {
        "block_id": build_block_id(identity["page_id"], "paragraph", 0),
        "block_type": BlockType.PARAGRAPH,
        "text": "A normal paragraph of text.",
        "page_number": 1,
        "reading_order": 0,
        "source_layer": TextLayer.NATIVE,
        "extraction_route": ExtractionRoute.NATIVE,
    }
    values.update(overrides)
    return BlockResult(**values)


def test_block_valid_and_language_optional(identity):
    block = _block(identity)
    assert block.block_type == BlockType.PARAGRAPH
    assert block.bbox is None


def test_block_metadata_rejects_absolute_private_path(identity):
    with pytest.raises(ValueError, match="absolute private path"):
        _block(identity, metadata={"origin": "C:\\Users\\alice\\secret.pdf"})


def test_block_metadata_rejects_secret_key(identity):
    with pytest.raises(ValueError, match="secret field"):
        _block(identity, metadata={"api_key": "abc123"})


def test_block_bbox_must_be_well_formed(identity):
    with pytest.raises(ValueError, match="bbox"):
        _block(identity, bbox=(10.0, 10.0, 5.0, 20.0))


def test_table_block_requires_table_payload(identity):
    with pytest.raises(ValueError, match="table payload"):
        _block(identity, block_type=BlockType.TABLE, text="table")


def test_non_table_block_rejects_table_payload(identity):
    table = TableResult(num_rows=1, num_cols=1, cells=[TableCell(row_index=0, col_index=0, text="x")])
    with pytest.raises(ValueError, match="Only table blocks"):
        _block(identity, block_type=BlockType.PARAGRAPH, table=table)


def test_table_cell_bounds_validated():
    with pytest.raises(ValueError, match="exceeds the declared"):
        TableResult(
            num_rows=1,
            num_cols=1,
            cells=[TableCell(row_index=1, col_index=0, text="out of range")],
        )
