"""Authentication + authorization dependencies.

Guards are written as reusable FastAPI dependencies and applied declaratively per
route. Permission checks never live inline in an endpoint body — a check that
lives in a function body is a check someone forgets to add to the next endpoint.

Resolution order for any protected endpoint (per the spec):
  1. Valid JWT?                          no  -> 401   (current_user)
  2. level == creator?                   yes -> allow, skip everything else
  3. requires admin panel & level user?  yes -> 403
  4. required permission in effective set? no -> 403
  5. allow
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from api.models import Level
from api.security import decode_token

# tokenUrl points at the OAuth2 password endpoint so Swagger's Authorize works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


@dataclass
class CurrentUser:
    """Identity reconstructed from the JWT — no DB hit on the hot path."""
    username: str
    level: Level
    tenant_id: str
    acl_groups: list[str]
    permissions: list[str]

    @property
    def is_creator(self) -> bool:
        return self.level == Level.creator

    @property
    def has_admin_panel(self) -> bool:
        return self.level in (Level.creator, Level.admin)


def current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """Step 1: valid JWT, else 401."""
    claims = decode_token(token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توکن نامعتبر است",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        level = Level(claims["level"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="توکن ناقص است",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(
        username=claims["sub"],
        level=level,
        tenant_id=claims["tenant_id"],
        acl_groups=claims.get("acl_groups", []),
        permissions=claims.get("permissions", []),
    )


def require_admin_panel(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Steps 2-3: creator passes; admin passes; user is refused entry."""
    if user.is_creator:
        return user
    if not user.has_admin_panel:  # level == user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="دسترسی به پنل مدیریت مجاز نیست",
        )
    return user


def require_creator(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_creator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="فقط سازنده مجاز است",
        )
    return user


def require_permission(permission: str):
    """Build a dependency enforcing the full resolution order for `permission`.

    All /admin/* routes go through this, so admin-panel gating (step 3) is folded
    in here: a `user`-level caller is refused before any permission is consulted.
    """
    def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.is_creator:                     # step 2
            return user
        if not user.has_admin_panel:            # step 3
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="دسترسی به پنل مدیریت مجاز نیست",
            )
        if permission not in user.permissions:  # step 4
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"نیازمند دسترسی «{permission}» هستید",
            )
        return user                             # step 5

    return dependency
