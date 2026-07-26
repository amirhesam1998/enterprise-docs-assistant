"""Document ingestion endpoints.

Gated by `documents.upload` through the same `require_permission` dependency the
admin panel uses — no inline permission checks.

The uploaded document's ACL identity (tenant_id + acl_groups) is read off the
caller's token and nothing else. There is no request-body field that can set
either one, exactly as /ask takes its pre-filter from the token rather than from
the client.
"""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from api.auth import CurrentUser, require_permission
from api.celery_app import celery_app
from api.config import UPLOAD_DIR
from api.schemas import JobStatus, UploadAccepted
from api.tasks import ingest_document
from eda.parse import PARSERS

router = APIRouter(prefix="/documents", tags=["documents"])

# Derived from the parser registry rather than restated: the registry is the one
# place a new format is declared, and a second hardcoded list here would drift
# from it — rejecting at the door a format the worker can actually ingest.
ALLOWED = frozenset(PARSERS)


@router.post("/upload", response_model=UploadAccepted,
             status_code=status.HTTP_202_ACCEPTED)
def upload(
    file: UploadFile,
    actor: CurrentUser = Depends(require_permission("documents.upload")),
):
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نام فایل الزامی است")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"فرمت پشتیبانی نمی‌شود: {ext}"
        )

    # The stored name is a fresh UUID: the client's filename is kept only as the
    # display `source`, so it can never steer where the file is written.
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{ext}")
    with open(saved, "wb") as f:
        f.write(file.file.read())

    # Queued, not awaited — the model load and the embedding pass belong to the
    # worker. tenant/ACL come from the token (see module docstring).
    task = ingest_document.delay(
        saved,              # parse_any reads the format off this path's extension
        actor.tenant_id,    # ← from token (ACL), not from the request
        file.filename,
        actor.acl_groups,   # ← from token (ACL), not from the request
    )

    return UploadAccepted(job_id=task.id, source=file.filename)


@router.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(
    job_id: str,
    actor: CurrentUser = Depends(require_permission("documents.upload")),
):
    result = celery_app.AsyncResult(job_id)
    resp = JobStatus(job_id=job_id, status=result.status)

    if result.successful():
        payload = result.result or {}
        # A finished job names the document it ingested, so it is scoped to the
        # tenant that owns it — a job from another tenant reads as unknown.
        if not actor.is_creator and payload.get("tenant_id") != actor.tenant_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "کار یافت نشد")
        resp.result = payload
    elif result.failed():
        resp.error = str(result.result)

    return resp
