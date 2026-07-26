"""Admin panel endpoints. Every route is gated by a permission dependency; there
are no inline permission checks. Endpoint bodies contain only integrity guard
rails (last-creator, self-demotion, grant-what-you-hold), which are business
constraints rather than access checks.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth import CurrentUser, require_permission
from api.config import DEFAULT_TENANT
from api.db import get_db
from api.models import Level, Permission, Role, User
from api.schemas import (
    PermissionAttach,
    PermissionCreate,
    PermissionOut,
    RoleAssign,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from api.security import hash_password
from api.serializers import serialize_user

router = APIRouter(prefix="/admin", tags=["admin"])


# --- shared helpers -------------------------------------------------------
def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "کاربر یافت نشد")
    return user


def _get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نقش یافت نشد")
    return role


def _get_permission(db: Session, perm_id: int) -> Permission:
    perm = db.get(Permission, perm_id)
    if perm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "دسترسی یافت نشد")
    return perm


def _creator_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.level == Level.creator)
    )


def _ensure_can_grant(actor: CurrentUser, perm_names: set[str]) -> None:
    """An admin cannot grant a permission they do not themselves hold."""
    if actor.is_creator:
        return
    missing = perm_names - set(actor.permissions)
    if missing:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"نمی‌توانید دسترسی‌ای که خودتان ندارید اعطا کنید: {', '.join(sorted(missing))}",
        )


def _ensure_level_change_allowed(actor: CurrentUser, level: Level) -> None:
    """Only a creator may mint admins or creators — creators manage admins."""
    if actor.is_creator:
        return
    if level in (Level.admin, Level.creator):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "فقط سازنده می‌تواند سطح admin یا creator تعیین کند",
        )


# ========================= USERS =========================
@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("users.read")),
):
    users = db.scalars(select(User).order_by(User.id)).all()
    return [serialize_user(u) for u in users]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("users.write")),
):
    _ensure_level_change_allowed(actor, body.level)
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "این نام کاربری قبلاً وجود دارد")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        level=body.level,
        tenant_id=body.tenant_id or DEFAULT_TENANT,
        acl_groups=body.acl_groups,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("users.write")),
):
    user = _get_user(db, user_id)

    if body.level is not None and body.level != user.level:
        _ensure_level_change_allowed(actor, body.level)
        # Guard rail: cannot demote yourself, and cannot demote the last creator.
        if user.username == actor.username:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "نمی‌توانید سطح خود را تغییر دهید")
        if user.level == Level.creator and body.level != Level.creator \
                and _creator_count(db) <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "آخرین سازنده را نمی‌توان تنزل داد")
        user.level = body.level

    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.email is not None:
        user.email = body.email
    if body.tenant_id is not None:
        user.tenant_id = body.tenant_id
    if body.acl_groups is not None:
        user.acl_groups = body.acl_groups

    db.commit()
    db.refresh(user)
    return serialize_user(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("users.delete")),
):
    user = _get_user(db, user_id)
    if user.username == actor.username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "نمی‌توانید خودتان را حذف کنید")
    if user.level == Level.creator and _creator_count(db) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "آخرین سازنده را نمی‌توان حذف کرد")
    db.delete(user)
    db.commit()


@router.post("/users/{user_id}/roles", response_model=UserOut)
def assign_role(
    user_id: int,
    body: RoleAssign,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("users.write")),
):
    user = _get_user(db, user_id)
    role = _get_role(db, body.role_id)
    _ensure_can_grant(actor, {p.name for p in role.permissions})
    if role not in user.roles:
        user.roles.append(role)
        db.commit()
        db.refresh(user)
    return serialize_user(user)


@router.delete("/users/{user_id}/roles/{role_id}", response_model=UserOut)
def unassign_role(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("users.write")),
):
    user = _get_user(db, user_id)
    role = _get_role(db, role_id)
    if role in user.roles:
        user.roles.remove(role)
        db.commit()
        db.refresh(user)
    return serialize_user(user)


# ========================= ROLES =========================
@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("roles.read")),
):
    return db.scalars(select(Role).order_by(Role.id)).all()


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("roles.write")),
):
    if db.scalar(select(Role).where(Role.name == body.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "نقشی با این نام وجود دارد")
    perms = db.scalars(
        select(Permission).where(Permission.id.in_(body.permission_ids))
    ).all()
    _ensure_can_grant(actor, {p.name for p in perms})
    role = Role(name=body.name, description=body.description, permissions=list(perms))
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.patch("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: int,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("roles.write")),
):
    role = _get_role(db, role_id)
    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    db.commit()
    db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("roles.write")),
):
    role = _get_role(db, role_id)
    # Deleting the Role clears its rows in user_roles / role_permissions, so users
    # are detached rather than left pointing at an orphaned id.
    db.delete(role)
    db.commit()


@router.post("/roles/{role_id}/permissions", response_model=RoleOut)
def attach_permission(
    role_id: int,
    body: PermissionAttach,
    db: Session = Depends(get_db),
    actor: CurrentUser = Depends(require_permission("roles.write")),
):
    role = _get_role(db, role_id)
    perm = _get_permission(db, body.permission_id)
    _ensure_can_grant(actor, {perm.name})
    if perm not in role.permissions:
        role.permissions.append(perm)
        db.commit()
        db.refresh(role)
    return role


@router.delete("/roles/{role_id}/permissions/{perm_id}", response_model=RoleOut)
def detach_permission(
    role_id: int,
    perm_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("roles.write")),
):
    role = _get_role(db, role_id)
    perm = _get_permission(db, perm_id)
    if perm in role.permissions:
        role.permissions.remove(perm)
        db.commit()
        db.refresh(role)
    return role


# ====================== PERMISSIONS ======================
@router.get("/permissions", response_model=list[PermissionOut])
def list_permissions(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("permissions.read")),
):
    return db.scalars(select(Permission).order_by(Permission.id)).all()


@router.post(
    "/permissions", response_model=PermissionOut, status_code=status.HTTP_201_CREATED
)
def create_permission(
    body: PermissionCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("permissions.write")),
):
    if db.scalar(select(Permission).where(Permission.name == body.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "دسترسی‌ای با این نام وجود دارد")
    perm = Permission(name=body.name, description=body.description)
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


@router.delete("/permissions/{perm_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_permission(
    perm_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_permission("permissions.write")),
):
    perm = _get_permission(db, perm_id)
    db.delete(perm)
    db.commit()
