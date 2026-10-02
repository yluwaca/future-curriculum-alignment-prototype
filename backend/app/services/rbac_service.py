import time
from typing import Set

from sqlalchemy.orm import Session

from app.models.user_role import UserRole
from app.models.role_permission import RolePermission
from app.models.permission import Permission

# In-memory cache: {identity_id: (permissions_set, expiry_timestamp)}
_PERMISSION_CACHE: dict[str, tuple[set[str], float]] = {}
CACHE_TTL_SECONDS: int = 60


def get_user_permissions(db: Session, identity_id: str) -> set[str]:
    """
    Retrieve all permissions assigned to a user via their roles.
    Uses a short-lived in-memory cache to reduce database load.
    """
    now = time.time()
    cached = _PERMISSION_CACHE.get(identity_id)

    if cached:
        permissions, expiry = cached
        if now < expiry:
            return permissions

    # Query fresh permissions from DB
    db_permissions = (
        db.query(Permission.permission_id)
        .join(RolePermission, Permission.permission_id == RolePermission.permission_id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .filter(UserRole.identity_id == identity_id)
        .all()
    )
    permissions = {row[0] for row in db_permissions}

    # Update cache
    _PERMISSION_CACHE[identity_id] = (permissions, now + CACHE_TTL_SECONDS)
    return permissions


def user_has_permission(db: Session, identity_id: str, permission: str) -> bool:
    """
    Check if a specific user holds the required permission.
    """
    permissions = get_user_permissions(db, identity_id)
    return permission in permissions


def invalidate_permission_cache(identity_id: str) -> None:
    """
    Clear cached permissions for a user. 
    Call this whenever role assignments are modified.
    """
    _PERMISSION_CACHE.pop(identity_id, None)