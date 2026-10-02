# backend/app/services/auth_service.py

"""
Authentication domain service.

Architecture:

- Access Token = Stateless JWT
- Refresh Token = Stateful Session
- Auditability = JTI Tracking
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_password,
    verify_token,
)

from app.models.auth_token import AuthToken
from app.models.user import User

# =========================================================
# Constants
# =========================================================

MAX_FAILED_LOGINS = 5

# =========================================================
# User Authentication
# =========================================================


def login_user(
    db: Session,
    identity_id: str,
    password: str,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Authenticate a user and establish a refresh session.
    """

    user = (
        db.query(User)
        .filter(
            (User.identity_id == identity_id)
            | (User.email == identity_id)
        )
        .first()
    )

    if user is None:
        return None

    # -----------------------------------------------------
    # Account Status
    # -----------------------------------------------------

    if not user.is_active:
        return None

    # -----------------------------------------------------
    # Locked Account Check
    # -----------------------------------------------------

    if (
        getattr(user, "locked_until", None)
        and user.locked_until > datetime.now(timezone.utc)
    ):
        return None

    # -----------------------------------------------------
    # Password Validation
    # -----------------------------------------------------

    if not verify_password(
        password,
        user.password_hash,
    ):

        user.failed_login_attempts = (
            user.failed_login_attempts or 0
        ) + 1

        if (
            user.failed_login_attempts
            >= MAX_FAILED_LOGINS
        ):
            user.is_active = False

        db.commit()

        return None

    # -----------------------------------------------------
    # Reset Failed Attempts
    # -----------------------------------------------------

    user.failed_login_attempts = 0

    # -----------------------------------------------------
    # Create Access Token
    # -----------------------------------------------------

    access_token = create_access_token(
        {
            "sub": user.identity_id,
            "email": user.email,
            "identity_type": user.identity_type,
        }
    )

    access_payload = verify_token(
        access_token,
        expected_type="access",
    )

    access_jti = access_payload.get("jti")

    # -----------------------------------------------------
    # Create Refresh Token
    # -----------------------------------------------------

    refresh_token = create_refresh_token(
        user.identity_id
    )

    refresh_payload = verify_token(
        refresh_token,
        expected_type="refresh",
    )

    refresh_jti = refresh_payload.get("jti")

    # -----------------------------------------------------
    # Persist Refresh Session
    # -----------------------------------------------------

    refresh_session = AuthToken(
        token_hash=hash_token(
            refresh_token
        ),
        token_type="refresh",
        subject_id=user.identity_id,
        subject_type=user.identity_type,
        issued_by="future-platform",
        expires_at=datetime.fromtimestamp(
            refresh_payload["exp"],
            tz=timezone.utc,
        ),
        ip_address=client_ip,
        user_agent=user_agent,
        token_metadata={
            "refresh_jti": refresh_jti,
            "access_jti": access_jti,
        },
    )

    db.add(refresh_session)

    # -----------------------------------------------------
    # Update User Activity
    # -----------------------------------------------------

    user.last_login_at = datetime.now(
        timezone.utc
    )

    db.commit()

    # -----------------------------------------------------
    # Return Authentication Context
    # -----------------------------------------------------

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "identity_id": user.identity_id,
        "email": user.email,
        "access_jti": access_jti,
        "refresh_jti": refresh_jti,
    }


# =========================================================
# Refresh Token Validation
# =========================================================


def validate_refresh_token(
    db: Session,
    refresh_token: str,
) -> Optional[AuthToken]:
    """
    Validate persisted refresh token.
    """

    token_hash = hash_token(
        refresh_token
    )

    session = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == token_hash,
            AuthToken.revoked.is_(False),
        )
        .first()
    )

    if session is None:
        return None

    if (
        session.expires_at
        < datetime.now(timezone.utc)
    ):
        return None

    session.last_used_at = datetime.now(
        timezone.utc
    )

    db.commit()

    return session


# =========================================================
# Session Revocation
# =========================================================


def revoke_refresh_token(
    db: Session,
    refresh_token: str,
) -> bool:
    """
    Revoke a refresh token session.
    """

    token_hash = hash_token(
        refresh_token
    )

    session = (
        db.query(AuthToken)
        .filter(
            AuthToken.token_hash == token_hash
        )
        .first()
    )

    if session is None:
        return False

    session.revoked = True
    session.revoked_at = datetime.now(
        timezone.utc
    )

    db.commit()

    return True


# =========================================================
# Revoke All User Sessions
# =========================================================


def revoke_all_user_sessions(
    db: Session,
    identity_id: str,
) -> int:
    """
    Revoke all active refresh sessions.
    """

    sessions = (
        db.query(AuthToken)
        .filter(
            AuthToken.subject_id == identity_id,
            AuthToken.revoked.is_(False),
        )
        .all()
    )

    count = 0

    for session in sessions:

        session.revoked = True
        session.revoked_at = datetime.now(
            timezone.utc
        )

        count += 1

    db.commit()

    return count