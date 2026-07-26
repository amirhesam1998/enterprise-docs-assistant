"""ORM models.

The `users` table intentionally carries BOTH authorization axes and they must
not be conflated:

  * ACL  (document access): `tenant_id` + `acl_groups`. Consumed by the Qdrant
    pre-filter in rag.py. Untouched by RBAC logic.
  * RBAC (feature access):  `level` + `roles` -> effective `permissions`. Gates
    API endpoints and UI surfaces, never document retrieval.
"""
import enum

from sqlalchemy import (
    Column,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base


class Level(str, enum.Enum):
    """Fixed, hierarchical RBAC level. Gates *entry*; roles gate *capability*."""
    creator = "creator"  # bypasses every permission check; manages admins
    admin = "admin"      # may enter the admin panel; capability comes from roles
    user = "user"        # never has admin panel access, regardless of roles held


# --- association tables (many-to-many) ---
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # granular capability named "resource.action", e.g. "users.read"
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str] = mapped_column(String, default="")

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str] = mapped_column(String, default="")

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions,
        back_populates="roles",
        lazy="selectin",
    )
    users: Mapped[list["User"]] = relationship(
        secondary=user_roles, back_populates="roles"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str] = mapped_column(String)

    # RBAC axis
    level: Mapped[Level] = mapped_column(
        Enum(Level, native_enum=False), default=Level.user
    )
    roles: Mapped[list[Role]] = relationship(
        secondary=user_roles,
        back_populates="users",
        lazy="selectin",
    )

    # ACL axis — do not repurpose these for feature gating
    tenant_id: Mapped[str] = mapped_column(String)
    acl_groups: Mapped[list] = mapped_column(JSON, default=list)

    @property
    def effective_permissions(self) -> list[str]:
        """Union of permission names across all roles held. A creator's real
        power is unconditional (checked by level), so this list is informational
        for them rather than exhaustive."""
        names = {p.name for role in self.roles for p in role.permissions}
        return sorted(names)
