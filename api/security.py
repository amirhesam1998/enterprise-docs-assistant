"""Password hashing (bcrypt via passlib) and JWT primitives.

The JWT bakes in the caller's effective permissions. This avoids a DB round-trip
on every protected request, at the cost of staleness: a permission revoked
mid-session stays effective until the token expires. TOKEN_MINUTES (60) bounds
that window. This is a real trade-off, not a free optimisation.
"""
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from api.config import ALGORITHM, SECRET_KEY, TOKEN_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(*, sub: str, level: str, tenant_id: str,
                        acl_groups: list[str], permissions: list[str]) -> str:
    payload = {
        "sub": sub,
        "level": level,
        "tenant_id": tenant_id,
        "acl_groups": acl_groups,
        "permissions": permissions,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Return the claims, or None if the token is forged/expired/malformed."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
