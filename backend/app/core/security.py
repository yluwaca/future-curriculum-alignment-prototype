"""
Security utilities for authentication,
JWT handling, password hashing,
session tracking, and security middleware.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from datetime import (
    datetime,
    timedelta,
    timezone,
)

from typing import (
    Any,
    Dict,
    Optional,
)

from fastapi import (
    FastAPI,
    HTTPException,
    status,
)

from jose import (
    JWTError,
    jwt,
)

from passlib.context import (
    CryptContext,
)

from app.core.config import (
    settings,
)

# =========================================================
# Password Hashing
# =========================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)

# =========================================================
# JWT Configuration
# =========================================================

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM

JWT_AUDIENCE = settings.JWT_AUDIENCE
JWT_ISSUER = settings.JWT_ISSUER

# =========================================================
# Password Utilities
# =========================================================


def hash_password(
    password: str,
) -> str:
    """
    Hash password.
    """

    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """
    Verify password.
    """

    return pwd_context.verify(
        plain_password,
        hashed_password,
    )


# =========================================================
# Session Utilities
# =========================================================


def create_session_id() -> str:
    """
    Generate session identifier.

    Session ID becomes:

    - JWT JTI
    - SEC01_AuthToken.token_id
    - DSL01_AuditEvent.token_id
    """

    return str(uuid.uuid4())


# =========================================================
# JWT Utilities
# =========================================================


def create_access_token(
    data: Dict[str, Any],
    session_id: str,
    expires_delta: Optional[
        timedelta
    ] = None,
) -> str:
    """
    Create access token.

    IMPORTANT:
    Uses session_id as JTI.
    """

    now = datetime.now(
        timezone.utc
    )

    expire = (
        now + expires_delta
        if expires_delta
        else now
        + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    payload = data.copy()

    payload.update(
        {
            "jti": session_id,
            "type": "access",
            "iat": now,
            "nbf": now,
            "exp": expire,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        }
    )

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_refresh_token(
    user_id: str,
    session_id: str,
) -> str:
    """
    Create refresh token.

    IMPORTANT:
    Uses SAME session_id.
    """

    now = datetime.now(
        timezone.utc
    )

    expire = now + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )

    payload = {
        "sub": user_id,
        "jti": session_id,
        "type": "refresh",
        "iat": now,
        "nbf": now,
        "exp": expire,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def verify_token(
    token: str,
    expected_type: Optional[
        str
    ] = None,
) -> Dict[str, Any]:
    """
    Validate JWT.
    """

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
            options={
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )

        token_type = payload.get(
            "type"
        )

        if (
            expected_type
            and token_type != expected_type
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        required_claims = [
            "sub",
            "jti",
            "type",
            "exp",
        ]

        for claim in required_claims:

            if claim not in payload:

                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"Missing claim: {claim}"
                    ),
                )

        return payload

    except JWTError as exc:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


# =========================================================
# Token Utilities
# =========================================================


def hash_token(
    token: str,
) -> str:
    """
    SHA256 token hash.
    """

    return hashlib.sha256(
        token.encode(
            "utf-8"
        )
    ).hexdigest()


def generate_secure_token(
    length: int = 32,
) -> str:
    """
    Generate secure token.
    """

    return secrets.token_urlsafe(
        length
    )


def get_token_expiry_seconds(
    exp_timestamp: int,
) -> int:
    """
    Remaining token lifetime.
    """

    now = int(
        datetime.now(
            timezone.utc
        ).timestamp()
    )

    return max(
        0,
        exp_timestamp - now,
    )


def extract_token_metadata(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract token metadata.
    """

    return {
        "subject": payload.get(
            "sub"
        ),
        "token_id": payload.get(
            "jti"
        ),
        "token_type": payload.get(
            "type"
        ),
        "issuer": payload.get(
            "iss"
        ),
        "audience": payload.get(
            "aud"
        ),
    }

# =========================================================
# Security Headers Middleware
# =========================================================


def setup_security_headers(
    app: FastAPI,
    settings_obj: Any,
) -> None:
    """
    Configure HTTP security headers.
    """

    @app.middleware("http")
    async def add_security_headers(
        request,
        call_next,
    ):
        response = await call_next(request)

        path = request.url.path

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

        response.headers[
            "Referrer-Policy"
        ] = (
            "strict-origin-when-cross-origin"
        )

        response.headers[
            "Permissions-Policy"
        ] = (
            "camera=(), "
            "microphone=(), "
            "geolocation=()"
        )

        swagger_paths = [
            "/docs",
            "/redoc",
            "/openapi.json",
        ]

        is_swagger_request = any(
            path.startswith(
                swagger_path
            )
            for swagger_path in swagger_paths
        )

        if is_swagger_request:

            csp = (
                "default-src 'self' https: data: blob:; "
                "script-src 'self' 'unsafe-inline' "
                "'unsafe-eval' https:; "
                "style-src 'self' 'unsafe-inline' https:; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https:;"
            )

        elif settings_obj.DEBUG:

            csp = (
                "default-src 'self'; "
                "script-src 'self' "
                "'unsafe-inline' "
                "'unsafe-eval'; "
                "style-src 'self' "
                "'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:;"
            )

        else:

            csp = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:;"
            )

        response.headers[
            "Content-Security-Policy"
        ] = csp

        if not is_swagger_request:

            response.headers[
                "Cross-Origin-Opener-Policy"
            ] = "same-origin"

            response.headers[
                "Cross-Origin-Resource-Policy"
            ] = "same-origin"

        if settings_obj.is_production:

            response.headers[
                "Strict-Transport-Security"
            ] = (
                "max-age=31536000; "
                "includeSubDomains"
            )

        return response
