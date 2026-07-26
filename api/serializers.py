"""Hand-built serializers where a model attribute doesn't map 1:1 to the schema.

Notably `UserOut.permissions` is the *effective* set (union across roles), which
is a computed property on the model rather than a column, so Pydantic's
from_attributes cannot infer it.
"""
from api.models import User
from api.schemas import RoleBrief, UserOut


def serialize_user(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        level=user.level,
        tenant_id=user.tenant_id,
        acl_groups=list(user.acl_groups or []),
        roles=[RoleBrief(id=r.id, name=r.name) for r in user.roles],
        permissions=user.effective_permissions,
    )
