from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eda.identifiers import document_id, page_id, revision_id
from eda.ingestion_schema import (
    ExtractionRoute,
    OCRDecision,
    PageResult,
    PageType,
    ProcessingProvenance,
    ProcessingStatus,
)


@pytest.fixture
def identity() -> dict[str, str]:
    digest = "a" * 64
    document = document_id("tenant-a", "dms:policy-42")
    revision = revision_id(document, digest)
    return {
        "digest": digest,
        "document_id": document,
        "revision_id": revision,
        "page_id": page_id(revision, 0),
    }


@pytest.fixture
def provenance(identity) -> ProcessingProvenance:
    return ProcessingProvenance(
        pipeline_name="contract-test",
        pipeline_version="1.0",
        input_sha256=identity["digest"],
        dpi=220,
        requested_language_profiles=["fas+eng"],
        resolved_language_profiles=["fas+eng"],
        python_version="3.12",
        tesseract_version="test-double",
        pymupdf_version="test-double",
        opencv_version="test-double",
        platform="synthetic-test",
        processing_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def page_factory(identity, provenance):
    def factory(**overrides) -> PageResult:
        values = {
            "document_id": identity["document_id"],
            "revision_id": identity["revision_id"],
            "page_id": identity["page_id"],
            "page_index": 0,
            "page_number": 1,
            "page_type": PageType.DIGITAL,
            "processing_status": ProcessingStatus.ACCEPTED,
            "native_text": "synthetic native text",
            "ocr_text": "",
            "ocr_decision": OCRDecision(
                selected_route=ExtractionRoute.NATIVE,
                quality_gate_passed=True,
                candidate_count=0,
            ),
            "provenance": provenance,
        }
        values.update(overrides)
        return PageResult(**values)

    return factory


# ---------------------------------------------------------------------------
# FastAPI admin/RBAC test harness
# ---------------------------------------------------------------------------
# Reusable fixtures for exercising the admin API against an isolated in-memory
# database with injected identities. Two things make this safe and correct:
#
#   1. pythonpath includes "." (see pyproject.toml) so `api.*` imports resolve.
#   2. TestClient(app) is built WITHOUT the context-manager form, so the app
#      lifespan (which calls seed() and writes demo users into the REAL
#      data/app.db) never fires. Combined with overriding get_db, tests touch
#      ONLY the throwaway in-memory database created here.
#
# Identity of the ACTING user comes from an injected CurrentUser via the
# `current_user` dependency override (see `as_actor` / `make_actor`), NOT from
# the DB and NOT from a real JWT. The DB holds the *target* User rows that the
# admin endpoints read and mutate.
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import CurrentUser, current_user
from api.db import Base, get_db
from api.main import app
from api.models import Level, User
from api.security import hash_password


def make_actor(
    username: str,
    level: Level = Level.user,
    tenant_id: str = "public",
    acl_groups: list[str] | None = None,
    permissions: list[str] | None = None,
) -> CurrentUser:
    """Build a CurrentUser identity to inject as the acting caller.

    This mirrors what `current_user` reconstructs from a JWT, so overriding the
    dependency with `lambda: actor` drives the real permission gate in
    `require_permission` exactly as a live request would.
    """
    return CurrentUser(
        username=username,
        level=level,
        tenant_id=tenant_id,
        acl_groups=list(acl_groups or []),
        permissions=list(permissions or []),
    )


@pytest.fixture
def db_session() -> Iterator["sessionmaker"]:
    """Isolated in-memory SQLite bound to one shared connection.

    StaticPool + check_same_thread=False ensures the app (served from FastAPI's
    threadpool) and the test share the very same connection, so rows committed
    by one are visible to the other. Yields the sessionmaker so callers can open
    fresh sessions.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session) -> Iterator[TestClient]:
    """TestClient wired to the in-memory DB, with the lifespan/seed suppressed.

    get_db is overridden to yield sessions on the test engine. The plain (no
    context-manager) TestClient(app) means the app lifespan never runs, so the
    real data/app.db is never seeded or touched.
    """

    def override_get_db():
        db = db_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def as_actor(client):
    """Context manager to run requests as a chosen injected identity.

    Usage:
        with as_actor(make_actor("root", Level.creator, "kb", [], [])):
            r = client.get("/admin/users")

    Installs `current_user` -> the given actor for the duration of the block and
    restores the prior override (usually none) afterward. Returns the TestClient
    for convenience.
    """
    from contextlib import contextmanager

    @contextmanager
    def _as(actor: CurrentUser):
        previous = app.dependency_overrides.get(current_user)
        app.dependency_overrides[current_user] = lambda: actor
        try:
            yield client
        finally:
            if previous is None:
                app.dependency_overrides.pop(current_user, None)
            else:
                app.dependency_overrides[current_user] = previous

    return _as


@pytest.fixture
def seeded(db_session):
    """Populate the test DB with target users spanning two tenants.

    Returns a dict of created ids plus the tenant/group names, so later phases
    can reference concrete user ids and tenants. The ACTING admin identity is
    injected separately via make_actor / as_actor — these rows are the targets
    the admin endpoints read and mutate.

    Layout:
      - creator            : level creator, tenant "public"
      - admin_a            : level admin,  tenant "tenant-a", acl ["billing"]
      - user_a             : level user,   tenant "tenant-a", acl ["billing"]
      - user_b             : level user,   tenant "tenant-b", acl ["hr"]
    """
    session = db_session()
    try:
        creator = User(
            username="creator",
            email="creator@example.com",
            password_hash=hash_password("creator123"),
            level=Level.creator,
            tenant_id="public",
            acl_groups=[],
        )
        admin_a = User(
            username="admin_a",
            email="admin_a@example.com",
            password_hash=hash_password("pw"),
            level=Level.admin,
            tenant_id="tenant-a",
            acl_groups=["billing"],
        )
        user_a = User(
            username="user_a",
            email="user_a@example.com",
            password_hash=hash_password("pw"),
            level=Level.user,
            tenant_id="tenant-a",
            acl_groups=["billing"],
        )
        user_b = User(
            username="user_b",
            email="user_b@example.com",
            password_hash=hash_password("pw"),
            level=Level.user,
            tenant_id="tenant-b",
            acl_groups=["hr"],
        )
        session.add_all([creator, admin_a, user_a, user_b])
        session.commit()
        ids = {
            "creator": creator.id,
            "admin_a": admin_a.id,
            "user_a": user_a.id,
            "user_b": user_b.id,
        }
    finally:
        session.close()

    return {
        "ids": ids,
        "tenant_a": "tenant-a",
        "tenant_b": "tenant-b",
        "group_a": "billing",
        "group_b": "hr",
        "admin_a_permissions": ["users.read", "users.write", "users.delete"],
    }
