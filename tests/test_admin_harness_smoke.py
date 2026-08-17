"""Smoke tests proving the admin/RBAC harness in conftest.py works end-to-end.

These assert three things:
  1. The isolated in-memory DB is wired up and seeded users are readable.
  2. The REAL permission gate (require_permission) fires through the harness.
  3. A baseline positive write path works end-to-end for a tenant admin.
"""
from api.models import Level

from tests.conftest import make_actor


def test_creator_lists_seeded_users(seeded, as_actor):
    """GET /admin/users as the seeded creator -> 200 with the seeded users."""
    actor = make_actor("creator", Level.creator, "public", [], [])
    with as_actor(actor) as client:
        resp = client.get("/admin/users")

    assert resp.status_code == 200, resp.text
    usernames = {u["username"] for u in resp.json()}
    assert {"creator", "admin_a", "user_a", "user_b"} <= usernames


def test_user_without_read_permission_is_forbidden(seeded, as_actor):
    """GET /admin/users as an ordinary user with no perms -> 403.

    Proves the permission gate is genuinely enforced through the harness, not
    bypassed by the dependency override.
    """
    actor = make_actor("user_a", Level.user, "tenant-a", ["billing"], [])
    with as_actor(actor) as client:
        resp = client.get("/admin/users")

    assert resp.status_code == 403, resp.text


def test_tenant_admin_creates_user(seeded, as_actor):
    """POST /admin/users as tenant-A admin creating a user in tenant A -> 201."""
    actor = make_actor(
        "admin_a",
        Level.admin,
        "tenant-a",
        ["billing"],
        ["users.read", "users.write", "users.delete"],
    )
    body = {
        "username": "new_user_a",
        "password": "pw",
        "email": "new_user_a@example.com",
        "level": "user",
        "tenant_id": "tenant-a",
        "acl_groups": ["billing"],
    }
    with as_actor(actor) as client:
        resp = client.post("/admin/users", json=body)

    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["username"] == "new_user_a"
    assert created["tenant_id"] == "tenant-a"
