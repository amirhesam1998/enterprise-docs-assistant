import pytest
from openpyxl import Workbook

from eda.parse import parse_any, parse_xlsx


@pytest.fixture
def workbook_path(tmp_path):
    path = tmp_path / "fixture.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Knowledge"
    sheet.append(["reference", "body"])
    sheet.append(
        [
            "item-1",
            "Synthetic policy text long enough to be selected as an XLSX text column "
            "and emitted as a chunk without containing private document material.",
        ]
    )
    workbook.save(path)
    workbook.close()
    return path


def test_permitted_group_is_preserved_and_forbidden_group_is_absent(workbook_path):
    chunks = parse_xlsx(
        workbook_path,
        tenant_id="tenant-a",
        source="fixture.xlsx",
        acl_groups=["billing"],
    )
    assert chunks and all(chunk.tenant_id == "tenant-a" for chunk in chunks)
    assert all(chunk.acl_groups == ["billing"] for chunk in chunks)
    assert set(chunks[0].acl_groups).isdisjoint({"security"})


@pytest.mark.parametrize("groups", [None, [], [""], ["  "]])
def test_missing_or_blank_acl_fails_before_chunks_are_created(workbook_path, groups):
    with pytest.raises(ValueError, match="ACL"):
        parse_xlsx(
            workbook_path,
            tenant_id="tenant-a",
            source="fixture.xlsx",
            acl_groups=groups,
        )


def test_parse_any_does_not_turn_missing_xlsx_acl_public(workbook_path):
    with pytest.raises(ValueError, match="never treated as public access"):
        parse_any(
            workbook_path,
            tenant_id="tenant-a",
            source="fixture.xlsx",
        )
