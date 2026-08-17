"""Unit tests for the Phase-2 admin scope-guard helpers.

These exercise the three new helpers in `api.routers.admin` DIRECTLY — no HTTP,
no TestClient. The two pure-function guards (`_ensure_tenant_scope`,
`_ensure_acl_scope`) take only a constructed `CurrentUser`; `_get_user_in_scope`
also needs real `User` rows, supplied via the in-memory `db_session` fixture.

The contract under test:
  * A creator bypasses every scope guard.
  * A non-creator admin is confined to its own tenant and its own ACL groups.
  * Out-of-tenant users are hidden behind a 404 (NOT 403) so an admin cannot
    enumerate other tenants' users.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.models import Level, User
from api.routers.admin import (
    _ensure_acl_scope,
    _ensure_tenant_scope,
    _get_user_in_scope,
)
from api.security import hash_password
from tests.conftest import make_actor


# ---------------------------------------------------------------------------
# creator bypasses all three guards
# ---------------------------------------------------------------------------
def test_creator_bypasses_tenant_scope():
    creator = make_actor("root", Level.creator, tenant_id="public")
    # Wrong tenant would raise for an admin; a creator must sail through.
    assert _ensure_tenant_scope(creator, "some-other-tenant") is None


def test_creator_bypasses_acl_scope():
    creator = make_actor("root", Level.creator, tenant_id="public", acl_groups=[])
    # Groups the creator does not personally hold must still be grantable.
    assert _ensure_acl_scope(creator, ["billing", "hr", "legal"]) is None


def test_creator_bypasses_user_scope(db_session):
    creator = make_actor("root", Level.creator, tenant_id="public")
    session = db_session()
    try:
        u = User(
            username="target",
            email="target@example.com",
            password_hash=hash_password("pw"),
            level=Level.user,
            tenant_id="tenant-b",
            acl_groups=["hr"],
        )
        session.add(u)
        session.commit()
        uid = u.id
    finally:
        session.close()

    session = db_session()
    try:
        # Cross-tenant target, but actor is a creator -> returned, not hidden.
        got = _get_user_in_scope(session, uid, creator)
        assert got.id == uid
    finally:
        session.close()


# ---------------------------------------------------------------------------
# _ensure_tenant_scope
# ---------------------------------------------------------------------------
def test_tenant_scope_same_tenant_passes():
    admin = make_actor("admin_a", Level.admin, tenant_id="tenant-a")
    assert _ensure_tenant_scope(admin, "tenant-a") is None


def test_tenant_scope_different_tenant_raises_403():
    # NEGATIVE CONTROL: if the `if tenant_id != actor.tenant_id: raise` body were
    # deleted, `_ensure_tenant_scope` would return None and `pytest.raises` would
    # fail with DID NOT RAISE — so this test fails loudly if the guard is gone.
    admin = make_actor("admin_a", Level.admin, tenant_id="tenant-a")
    with pytest.raises(HTTPException) as exc:
        _ensure_tenant_scope(admin, "tenant-b")
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# _ensure_acl_scope
# ---------------------------------------------------------------------------
def test_acl_scope_subset_passes():
    admin = make_actor(
        "admin_a", Level.admin, tenant_id="tenant-a", acl_groups=["billing", "hr"]
    )
    assert _ensure_acl_scope(admin, ["billing"]) is None


def test_acl_scope_empty_list_passes():
    admin = make_actor(
        "admin_a", Level.admin, tenant_id="tenant-a", acl_groups=["billing"]
    )
    assert _ensure_acl_scope(admin, []) is None


def test_acl_scope_unheld_group_raises_403():
    admin = make_actor(
        "admin_a", Level.admin, tenant_id="tenant-a", acl_groups=["billing"]
    )
    with pytest.raises(HTTPException) as exc:
        _ensure_acl_scope(admin, ["billing", "legal"])
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# _get_user_in_scope
# ---------------------------------------------------------------------------
def _seed_users(db_session) -> dict[str, int]:
    session = db_session()
    try:
        same = User(
            username="user_a",
            email="user_a@example.com",
            password_hash=hash_password("pw"),
            level=Level.user,
            tenant_id="tenant-a",
            acl_groups=["billing"],
        )
        other = User(
            username="user_b",
            email="user_b@example.com",
            password_hash=hash_password("pw"),
            level=Level.user,
            tenant_id="tenant-b",
            acl_groups=["hr"],
        )
        session.add_all([same, other])
        session.commit()
        ids = {"same": same.id, "other": other.id}
    finally:
        session.close()
    return ids


def test_get_user_in_scope_same_tenant_returns_user(db_session):
    ids = _seed_users(db_session)
    admin = make_actor("admin_a", Level.admin, tenant_id="tenant-a")
    session = db_session()
    try:
        got = _get_user_in_scope(session, ids["same"], admin)
        assert got.id == ids["same"]
        assert got.tenant_id == "tenant-a"
    finally:
        session.close()


def test_get_user_in_scope_cross_tenant_raises_404(db_session):
    # NEGATIVE CONTROL: the enumeration-safety contract. If the
    # `if not actor.is_creator and user.tenant_id != actor.tenant_id: raise 404`
    # body were removed, the cross-tenant user would be returned instead of
    # hidden, `pytest.raises` would fail with DID NOT RAISE, and the leak would
    # be caught here. Also asserts 404 (NOT 403) — confirming existence is not
    # disclosed to an out-of-tenant admin.
    ids = _seed_users(db_session)
    admin = make_actor("admin_a", Level.admin, tenant_id="tenant-a")
    session = db_session()
    try:
        with pytest.raises(HTTPException) as exc:
            _get_user_in_scope(session, ids["other"], admin)
        assert exc.value.status_code == 404
    finally:
        session.close()


def test_get_user_in_scope_missing_id_raises_404(db_session):
    admin = make_actor("admin_a", Level.admin, tenant_id="tenant-a")
    session = db_session()
    try:
        with pytest.raises(HTTPException) as exc:
            _get_user_in_scope(session, 999999, admin)
        assert exc.value.status_code == 404
    finally:
        session.close()
