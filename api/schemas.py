"""Pydantic request/response models.

The signup schema is deliberately narrow: it accepts ONLY username, password,
and email. level / roles / tenant_id / acl_groups are never read from a signup
body — accepting them would be a privilege-escalation hole.
"""
from pydantic import BaseModel, ConfigDict, Field

from api.models import Level


# --- auth ---
class SignupRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    email: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RoleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class MeResponse(BaseModel):
    username: str
    level: Level
    tenant_id: str
    acl_groups: list[str]
    roles: list[RoleBrief]
    permissions: list[str]


# --- users (admin) ---
class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str = ""


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str = ""
    permissions: list[PermissionOut] = []


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str | None = None
    level: Level
    tenant_id: str
    acl_groups: list[str]
    roles: list[RoleBrief] = []
    permissions: list[str] = []  # effective (union across roles)


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    email: str | None = None
    level: Level = Level.user
    tenant_id: str | None = None      # falls back to configured default
    acl_groups: list[str] = []


class UserUpdate(BaseModel):
    password: str | None = None
    email: str | None = None
    level: Level | None = None
    tenant_id: str | None = None
    acl_groups: list[str] | None = None


class RoleAssign(BaseModel):
    role_id: int


# --- roles (admin) ---
class RoleCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PermissionAttach(BaseModel):
    permission_id: int


# --- permissions (admin) ---
class PermissionCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


# --- documents ---
# There is deliberately no upload *request* schema: the only input is the file
# itself. tenant_id and acl_groups come from the token, never from the body —
# the same rule that keeps SignupRequest narrow.
class UploadAccepted(BaseModel):
    job_id: str
    status: str = "queued"
    source: str


class JobStatus(BaseModel):
    job_id: str
    status: str  # PENDING | STARTED | SUCCESS | FAILURE
    result: dict | None = None
    error: str | None = None
