"""Phase 3 integration tests: tenant/ACL scope guards on the admin USER
mutation endpoints.

These exercise the real FastAPI admin router against the Phase-1 in-memory DB
harness (see tests/conftest.py). The acting identity is injected via `as_actor`
(overriding `current_user`), while `seeded` populates the target user rows that
span two tenants. Both fixtures share the SAME engine (Phase 1 wiring), so a row
committed by `seeded` is visible to requests issued through `client`.

Attack surface under test: a tenant-A admin must not be able to create, read,
modify, delete, or role-assign users that belong to another tenant, nor grant
ACL groups it does not itself hold; a creator bypasses all of it.
"""
from __future__ import annotations

from api.models import Level
from tests.conftest import make_actor


def _admin_a():
    """Tenant-A admin: scoped to tenant-a / billing, holds user.* perms."""
    return make_actor(
        "admin_a",
        level=Level.admin,
        tenant_id="tenant-a",
        acl_groups=["billing"],
        permissions=["users.read", "users.write", "users.delete"],
    )


def _creator():
    """Creator: unscoped, bypasses tenant/ACL guards."""
    return make_actor(
        "creator",
        level=Level.creator,
        tenant_id="public",
        acl_groups=[],
        permissions=[],
    )


# --------------------------------------------------------------------------
# create_user — tenant + ACL scope
# --------------------------------------------------------------------------
def test_create_user_in_other_tenant_is_forbidden(seeded, as_actor):
    # NEGATIVE CONTROL: if _ensure_tenant_scope were not wired into create_user,
    # this cross-tenant create would return 201 and this assertion would fail.
    with as_actor(_admin_a()) as client:
        r = client.post(
            "/admin/users",
            json={
                "username": "intruder",
                "password": "pw",
                "tenant_id": "tenant-b",
                "acl_groups": [],
            },
        )
    assert r.status_code == 403, r.text


def test_create_user_with_unheld_acl_group_is_forbidden(seeded, as_actor):
    with as_actor(_admin_a()) as client:
        r = client.post(
            "/admin/users",
            json={
                "username": "grabby",
                "password": "pw",
                "tenant_id": "tenant-a",
                "acl_groups": ["hr"],  # admin_a only holds "billing"
            },
        )
    assert r.status_code == 403, r.text


def test_create_user_in_own_tenant_with_held_group_succeeds(seeded, as_actor):
    with as_actor(_admin_a()) as client:
        r = client.post(
            "/admin/users",
            json={
                "username": "legit",
                "password": "pw",
                "tenant_id": "tenant-a",
                "acl_groups": ["billing"],
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tenant_id"] == "tenant-a"
    assert body["acl_groups"] == ["billing"]


# --------------------------------------------------------------------------
# update_user — scoped fetch hides cross-tenant targets (enumeration-safe 404)
# --------------------------------------------------------------------------
def test_patch_cross_tenant_user_password_is_404(seeded, as_actor):
    # NEGATIVE CONTROL: without _get_user_in_scope, this PATCH would locate the
    # tenant-B user and return 200; the scoped fetch turns it into a 404.
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"password": "hacked"})
    assert r.status_code == 404, r.text


def test_patch_cross_tenant_user_email_is_404(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"email": "evil@x.com"})
    assert r.status_code == 404, r.text


def test_patch_cross_tenant_user_tenant_is_404(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"tenant_id": "tenant-a"})
    assert r.status_code == 404, r.text


def test_patch_cross_tenant_user_acl_is_404(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"acl_groups": ["billing"]})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------
# delete_user / assign_role — scoped fetch
# --------------------------------------------------------------------------
def test_delete_cross_tenant_user_is_404(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.delete(f"/admin/users/{uid}")
    assert r.status_code == 404, r.text


def test_assign_role_cross_tenant_user_is_404(seeded, as_actor):
    # A 404 from _get_user_in_scope fires before any role lookup, so an arbitrary
    # (even nonexistent) role_id is fine — the body only needs to validate.
    uid = seeded["ids"]["user_b"]
    with as_actor(_admin_a()) as client:
        r = client.post(f"/admin/users/{uid}/roles", json={"role_id": 1})
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------
# list_users — scoped listing
# --------------------------------------------------------------------------
def test_list_users_scoped_to_own_tenant(seeded, as_actor):
    with as_actor(_admin_a()) as client:
        r = client.get("/admin/users")
    assert r.status_code == 200, r.text
    users = r.json()
    assert users, "expected at least the tenant-a rows"
    assert all(u["tenant_id"] == "tenant-a" for u in users), users
    usernames = {u["username"] for u in users}
    assert "user_b" not in usernames  # tenant-B user must be absent
    assert "creator" not in usernames  # public-tenant creator also absent


# --------------------------------------------------------------------------
# update_user tenant move — creators only
# --------------------------------------------------------------------------
def test_move_own_tenant_user_across_tenants_forbidden_for_admin(seeded, as_actor):
    # In-scope target (tenant-a), but moving it to another tenant is a structural
    # change reserved for creators -> 403 for the admin.
    uid = seeded["ids"]["user_a"]
    with as_actor(_admin_a()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"tenant_id": "tenant-b"})
    assert r.status_code == 403, r.text


def test_move_user_across_tenants_allowed_for_creator(seeded, as_actor):
    uid = seeded["ids"]["user_a"]
    with as_actor(_creator()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"tenant_id": "tenant-b"})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == "tenant-b"


# --------------------------------------------------------------------------
# creator bypass — representative cross-tenant actions all succeed
# --------------------------------------------------------------------------
def test_creator_can_create_in_any_tenant(seeded, as_actor):
    with as_actor(_creator()) as client:
        r = client.post(
            "/admin/users",
            json={
                "username": "cross_born",
                "password": "pw",
                "tenant_id": "tenant-b",
                "acl_groups": ["hr"],
            },
        )
    assert r.status_code == 201, r.text
    assert r.json()["tenant_id"] == "tenant-b"


def test_creator_list_users_sees_all_tenants(seeded, as_actor):
    with as_actor(_creator()) as client:
        r = client.get("/admin/users")
    assert r.status_code == 200, r.text
    tenants = {u["tenant_id"] for u in r.json()}
    assert {"public", "tenant-a", "tenant-b"} <= tenants, tenants


def test_creator_can_delete_cross_tenant_user(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_creator()) as client:
        r = client.delete(f"/admin/users/{uid}")
    assert r.status_code == 204, r.text


def test_creator_can_patch_cross_tenant_user(seeded, as_actor):
    uid = seeded["ids"]["user_b"]
    with as_actor(_creator()) as client:
        r = client.patch(f"/admin/users/{uid}", json={"email": "ok@x.com"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "ok@x.com"
