"""Idempotent startup seeding.

Creates the standard permissions, a few sensible roles, one creator account, and
migrates the five original demo users — preserving each user's tenant_id and
acl_groups EXACTLY, because the RAG demo depends on those values. Running this
repeatedly is a no-op: every object is looked up by its unique key before insert,
and role/permission wiring is only applied when the row is first created, so
runtime edits made through the API are never clobbered. The same rule governs the
first-run role grants in SEED_ROLE_GRANTS.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import CREATOR_EMAIL, CREATOR_PASSWORD, CREATOR_USERNAME
from api.db import Base, SessionLocal, engine
from api.models import Level, Permission, Role, User
from api.security import hash_password

# name -> description
STANDARD_PERMISSIONS = {
    "users.read": "View users",
    "users.write": "Create and edit users",
    "users.delete": "Delete users",
    "roles.read": "View roles",
    "roles.write": "Create, edit and delete roles",
    "permissions.read": "View permissions",
    "permissions.write": "Create and delete permissions",
    "documents.upload": "Upload documents for ingestion",
    "audit.read": "Read the audit log",
}

# role name -> (description, [permission names])
STANDARD_ROLES = {
    "User Manager": ("Read and write users", ["users.read", "users.write"]),
    "User Admin": (
        "Full user lifecycle including deletion",
        ["users.read", "users.write", "users.delete"],
    ),
    "Read Only": (
        "Read-only across users, roles and permissions",
        ["users.read", "roles.read", "permissions.read"],
    ),
    "Role Manager": ("Manage roles", ["roles.read", "roles.write"]),
    "Auditor": ("Read the audit log", ["audit.read"]),
    "Document Manager": ("Upload documents for ingestion", ["documents.upload"]),
}

# role name -> usernames granted it when the ROLE ROW IS FIRST CREATED.
# Deliberately keyed on role creation, not on every boot: re-asserting these on
# each startup would re-attach a role an admin had removed through the API, which
# is exactly the clobbering the rest of this module avoids.
SEED_ROLE_GRANTS = {
    "Document Manager": ["sara"],
}

# username -> (password, level, tenant_id, acl_groups, [role names])
DEMO_USERS = {
    "sara":   ("sara123",   Level.admin, "kb",            ["billing"],     ["User Manager"]),
    "reza":   ("reza123",   Level.admin, "kb",            ["security"],    ["Read Only"]),
    "ali":    ("ali123",    Level.user,  "postgres",      ["engineering"], []),
    "maryam": ("maryam123", Level.user,  "postgres",      ["hr"],          []),
    "dana":   ("dana123",   Level.user,  "acme-internal", ["sales"],       []),
}


def _get_or_create_permission(db: Session, name: str, description: str) -> Permission:
    perm = db.scalar(select(Permission).where(Permission.name == name))
    if perm is None:
        perm = Permission(name=name, description=description)
        db.add(perm)
        db.flush()
    return perm


def _get_or_create_role(db: Session, name: str, description: str,
                        perm_names: list[str]) -> tuple[Role, bool]:
    """Returns (role, created). `created` lets the caller wire up first-run-only
    grants without re-applying them on every subsequent boot."""
    role = db.scalar(select(Role).where(Role.name == name))
    if role is not None:
        return role, False
    perms = db.scalars(
        select(Permission).where(Permission.name.in_(perm_names))
    ).all()
    role = Role(name=name, description=description, permissions=list(perms))
    db.add(role)
    db.flush()
    return role, True


def _get_or_create_user(db: Session, username: str, password: str, level: Level,
                        tenant_id: str, acl_groups: list[str],
                        role_names: list[str], email: str | None = None) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        roles = db.scalars(select(Role).where(Role.name.in_(role_names))).all()
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            level=level,
            tenant_id=tenant_id,
            acl_groups=acl_groups,
            roles=list(roles),
        )
        db.add(user)
        db.flush()
    return user


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for name, desc in STANDARD_PERMISSIONS.items():
            _get_or_create_permission(db, name, desc)
        db.flush()

        new_roles = []
        for name, (desc, perm_names) in STANDARD_ROLES.items():
            role, created = _get_or_create_role(db, name, desc, perm_names)
            if created:
                new_roles.append(role)
        db.flush()

        _get_or_create_user(
            db, CREATOR_USERNAME, CREATOR_PASSWORD, Level.creator,
            tenant_id="kb", acl_groups=[], role_names=[], email=CREATOR_EMAIL,
        )
        for username, (pw, level, tenant, groups, roles) in DEMO_USERS.items():
            _get_or_create_user(db, username, pw, level, tenant, groups, roles)
        db.flush()

        # First-run-only grants, so a freshly added standard role reaches the demo
        # account that needs it even though that account already exists.
        for role in new_roles:
            for username in SEED_ROLE_GRANTS.get(role.name, []):
                user = db.scalar(select(User).where(User.username == username))
                if user is not None and role not in user.roles:
                    user.roles.append(role)

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
    print("Seed complete.")
