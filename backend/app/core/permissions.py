# backend/app/core/permissions.py

"""
Enterprise RBAC authorization layer.

Supports:

- Permission-based authorization
- Role-based authorization
- Any-of permission checks
- All-of permission checks
- Admin override
- Audit logging
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)

from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
    resolve_user_roles,
)

from app.db.session import (
    get_db,
)

from app.models.user import User
from app.models.user_role import UserRole

from app.services.rbac_service import (
    get_user_permissions,
    user_has_permission,
)

from app.services.audit_service import (
    log_access_denied,
)

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Admin Override
# =========================================================


def is_system_admin(
    user: User,
) -> bool:
    """
    System administrator bypass.
    """

    return bool(
        getattr(
            user,
            "is_admin",
            False,
        )
    )

# =========================================================
# Permission Check
# =========================================================


def require_permission(
    permission: str,
):
    """
    Require a single permission.

    Example:

        Depends(
            require_permission(
                "dataset.read"
            )
        )
    """

    async def permission_checker(
        request: Request,
        current_user: User = Depends(
            get_current_user
        ),
        db: Session = Depends(
            get_db
        ),
    ) -> User:

        strict_permission = permission == "recommendation.academic_approve"
        if is_system_admin(current_user) and not strict_permission:
            return current_user

        has_permission = (
            user_has_permission(
                db=db,
                identity_id=current_user.identity_id,
                permission=permission,
            )
        )

        if not has_permission:

            try:

                log_access_denied(
                    db=db,
                    identity_id=current_user.identity_id,
                    required_permission=permission,
                    resource=request.url.path,
                    method=request.method,
                    reason="insufficient_permission",
                )

            except Exception:

                logger.exception(
                    "Audit logging failed"
                )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Missing permission: "
                    f"{permission}"
                ),
            )

        return current_user

    return permission_checker

# =========================================================
# Any Permission
# =========================================================


def require_any_permission(
    permissions: List[str],
):
    """
    Require ANY permission.
    """

    async def permission_checker(
        request: Request,
        current_user: User = Depends(
            get_current_user
        ),
        db: Session = Depends(
            get_db
        ),
    ) -> User:

        if is_system_admin(
            current_user
        ):
            return current_user

        user_permissions = (
            get_user_permissions(
                db=db,
                identity_id=current_user.identity_id,
            )
        )

        granted = any(
            permission in user_permissions
            for permission in permissions
        )

        if not granted:

            try:

                log_access_denied(
                    db=db,
                    identity_id=current_user.identity_id,
                    required_permission=(
                        ",".join(
                            permissions
                        )
                    ),
                    resource=request.url.path,
                    method=request.method,
                    reason="missing_any_permission",
                )

            except Exception:

                logger.exception(
                    "Audit logging failed"
                )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "User lacks required "
                    "permissions"
                ),
            )

        return current_user

    return permission_checker

# =========================================================
# All Permissions
# =========================================================


def require_all_permissions(
    permissions: List[str],
):
    """
    Require ALL permissions.
    """

    async def permission_checker(
        request: Request,
        current_user: User = Depends(
            get_current_user
        ),
        db: Session = Depends(
            get_db
        ),
    ) -> User:

        if is_system_admin(
            current_user
        ):
            return current_user

        user_permissions = (
            get_user_permissions(
                db=db,
                identity_id=current_user.identity_id,
            )
        )

        missing = [
            permission
            for permission in permissions
            if permission
            not in user_permissions
        ]

        if missing:

            try:

                log_access_denied(
                    db=db,
                    identity_id=current_user.identity_id,
                    required_permission=(
                        ",".join(
                            missing
                        )
                    ),
                    resource=request.url.path,
                    method=request.method,
                    reason="missing_permissions",
                )

            except Exception:

                logger.exception(
                    "Audit logging failed"
                )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Missing permissions: "
                    f"{', '.join(missing)}"
                ),
            )

        return current_user

    return permission_checker

# =========================================================
# Role Check
# =========================================================


def require_role(
    role_name: str,
):
    """
    Require a role.

    Example:

        Depends(
            require_role(
                "ADMIN"
            )
        )
    """

    async def role_checker(
        request: Request,
        current_user: User = Depends(
            get_current_user
        ),
        db: Session = Depends(
            get_db
        ),
    ) -> User:

        if is_system_admin(
            current_user
        ):
            return current_user

        roles = resolve_user_roles(
            current_user
        )

        if (
            role_name.upper()
            not in roles
        ):

            try:

                log_access_denied(
                    db=db,
                    identity_id=current_user.identity_id,
                    required_permission=(
                        f"ROLE:{role_name}"
                    ),
                    resource=request.url.path,
                    method=request.method,
                    reason="missing_role",
                )

            except Exception:

                logger.exception(
                    "Audit logging failed"
                )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Missing role: "
                    f"{role_name}"
                ),
            )

        return current_user

    return role_checker

# =========================================================
# Current User Permissions
# =========================================================


def get_current_permissions(
    current_user: User,
    db: Session,
) -> set[str]:
    """
    Helper utility.
    """

    return get_user_permissions(
        db=db,
        identity_id=current_user.identity_id,
    )