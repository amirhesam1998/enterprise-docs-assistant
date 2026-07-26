"""FastAPI entrypoint.

Wires the auth + admin + documents routers, seeds the database on startup, and
keeps the two pre-existing endpoints (/health, /ask) with unchanged behaviour.
The /ask ACL pre-filter still runs off tenant_id + acl_groups carried in the token.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.auth import CurrentUser, current_user
from api.config import FRONTEND_ORIGIN
from api.rag import search_and_answer
from api.routers import admin, auth, documents
from api.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed()  # idempotent: create tables, standard perms/roles, creator, demo users
    yield


app = FastAPI(title="Enterprise Docs Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)

class AskRequest(BaseModel):
    question: str
    k: int = 5


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest, user: CurrentUser = Depends(current_user)):
    """Any authenticated user, any level. Documents are pre-filtered by the
    caller's tenant_id and acl_groups — the ACL axis, taken from the token,
    exactly as before. This retrieval filtering is unchanged."""
    return search_and_answer(
        question=req.question,
        tenant_id=user.tenant_id,   # ← from token (ACL), not RBAC
        user_groups=user.acl_groups,  # ← from token (ACL), not RBAC
        k=req.k,
    )
