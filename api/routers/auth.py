"""Auth endpoints: signup (public), login (OAuth2 form), me."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import CurrentUser, current_user
from api.config import DEFAULT_TENANT
from api.db import get_db
from api.models import Level, User
from api.schemas import MeResponse, RoleBrief, SignupRequest, Token, UserOut
from api.security import create_access_token, hash_password, verify_password
from api.serializers import serialize_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_token(user: User) -> str:
    return create_access_token(
        sub=user.username,
        level=user.level.value,
        tenant_id=user.tenant_id,
        acl_groups=list(user.acl_groups or []),
        permissions=user.effective_permissions,
    )


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    """Self-registration. ALWAYS creates a level-`user` account with the default
    tenant and no roles. level / roles / tenant / acl_groups are intentionally
    NOT read from the body — accepting them would be privilege escalation."""
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "این نام کاربری قبلاً ثبت شده است")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        level=Level.user,          # forced
        tenant_id=DEFAULT_TENANT,  # forced
        acl_groups=[],             # forced
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password form — the frontend depends on this form-based contract."""
    user = db.scalar(select(User).where(User.username == form.username))
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نام کاربری یا رمز اشتباه است",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=_issue_token(user))


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)):
    """Full identity the frontend renders its navigation from. Read fresh from the
    DB (not the token) so roles/permissions reflect the current state."""
    row = db.scalar(select(User).where(User.username == user.username))
    if row is None:  # token valid but user deleted since issuance
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "کاربر یافت نشد")
    return MeResponse(
        username=row.username,
        level=row.level,
        tenant_id=row.tenant_id,
        acl_groups=list(row.acl_groups or []),
        roles=[RoleBrief(id=r.id, name=r.name) for r in row.roles],
        permissions=row.effective_permissions,
    )
