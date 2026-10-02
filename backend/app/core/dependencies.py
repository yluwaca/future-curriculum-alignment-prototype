# backend/app/core/dependencies.py

"""
Authentication and authorization dependencies.

Architecture:

- Access Tokens = Stateless JWT
- Refresh Tokens = Stateful Sessions
- Audit Traceability = JTI

Provides:
- JWT authentication
- RBAC authorization
- request context injection
- session tracking
"""

from __future__ import annotations

from typing import Optional
from typing import Set

from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from sqlalchemy.orm import Session

from app.core.security import (
    verify_token,
)

from app.db.session import (
    get_db,
)

from app.models.user import (
    User,
)
from app.core.tenant_scope import require_user_tenant

# =========================================================
# HTTP Bearer
# =========================================================

security = HTTPBearer(
    auto_error=False,
)

# =========================================================
# Authentication Exception
# =========================================================


def authentication_exception(
    detail: str = "Authentication failed",
) -> HTTPException:
    """
    Standardized authentication exception.
    """

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )

# =========================================================
# Role Helpers
# =========================================================


def resolve_user_roles(
    user: User,
) -> Set[str]:
    """
    Resolve normalized role names from role IDs.
    """

    roles: Set[str] = set()

    if not hasattr(
        user,
        "roles",
    ):
        return roles

    for role in user.roles:

        role_id = getattr(
            role,
            "role_id",
            None,
        )

        if role_id:

            roles.add(
                role_id.upper()
            )

    return roles

# =========================================================
# Current User
# =========================================================


def get_current_user(
    request: Request,
    credentials: Optional[
        HTTPAuthorizationCredentials
    ] = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve authenticated user.
    """

    # -----------------------------------------------------
    # Authorization Header Validation
    # -----------------------------------------------------

    if (
        credentials is None
        or not credentials.credentials
    ):

        raise authentication_exception(
            "Missing bearer token"
        )

    token = credentials.credentials

    # -----------------------------------------------------
    # JWT Validation
    # -----------------------------------------------------

    payload = verify_token(
        token,
        expected_type="access",
    )

    subject_id = payload.get(
        "sub"
    )

    token_jti = payload.get(
        "jti"
    )

    if not subject_id:

        raise authentication_exception(
            "Missing subject claim"
        )

    if not token_jti:

        raise authentication_exception(
            "Missing JTI claim"
        )

    # -----------------------------------------------------
    # Resolve User
    # -----------------------------------------------------

    user = (
        db.query(User)
        .filter(
            User.identity_id
            == subject_id
        )
        .first()
    )

    if user is None:

        raise authentication_exception(
            "User not found"
        )

    # -----------------------------------------------------
    # Account Validation
    # -----------------------------------------------------

    if not user.is_active:

        raise authentication_exception(
            "User account inactive"
        )

    if getattr(
        user,
        "is_locked",
        False,
    ):

        raise authentication_exception(
            "User account locked"
        )

    # -----------------------------------------------------
    # Request Context
    # -----------------------------------------------------

    request.state.user = user

    request.state.user_id = (
        user.identity_id
    )

    request.state.token_id = (
        token_jti
    )

    request.state.token_payload = (
        payload
    )

    request.state.tenant_id = require_user_tenant(user)
    db.info["tenant_id"] = str(user.tenant_id)

    token_tenant_id = payload.get("tenant_id")
    if token_tenant_id and str(token_tenant_id) != str(user.tenant_id):
        raise authentication_exception("Token tenant context is stale")

    return user

# =========================================================
# Optional Current User
# =========================================================


def get_optional_current_user(
    request: Request,
    credentials: Optional[
        HTTPAuthorizationCredentials
    ] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Optional authentication.
    """

    try:

        if credentials is None:

            return None

        return get_current_user(
            request=request,
            credentials=credentials,
            db=db,
        )

    except Exception:

        return None

# =========================================================
# RBAC Factory
# =========================================================


def require_role(
    *roles: str,
):
    """
    Role-based authorization dependency.

    Example:

        Depends(
            require_role(
                "ADMIN",
                "DATA_SCIENTIST",
            )
        )
    """

    normalized_roles = {
        role.upper()
        for role in roles
    }

    async def role_checker(
        current_user: User = Depends(
            get_current_user
        ),
    ) -> User:

        # -------------------------------------------------
        # Admin Override
        # -------------------------------------------------

        strict_roles = {"CURRICULUM_APPROVER"}
        if (
            not normalized_roles.intersection(strict_roles)
            and getattr(current_user, "is_admin", False)
        ):
            return current_user

        user_roles = (
            resolve_user_roles(
                current_user
            )
        )

        if not any(
            role in user_roles
            for role in normalized_roles
        ):

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Insufficient permissions"
                ),
            )

        return current_user

    return role_checker

# =========================================================
# Role Resolution Dependency
# =========================================================


def get_current_user_roles(
    current_user: User = Depends(
        get_current_user
    ),
) -> Set[str]:
    """
    Return current user's roles.
    """

    return resolve_user_roles(
        current_user
    )

# =========================================================
# Session Context Dependency
# =========================================================


def get_current_session_id(
    request: Request,
) -> Optional[str]:
    """
    Return current session JTI.
    """

    return getattr(
        request.state,
        "token_id",
        None,
    )
