# backend/app/schemas/__init__.py

"""
FUTURE Platform Schema Registry.

Central export point for all Pydantic schemas.
"""

# =========================================================
# Authentication Schemas
# =========================================================

from app.schemas.auth import (
    LoginRequest,
    LogoutResponse,
    PasswordChangeRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)

# =========================================================
# Exports
# =========================================================

__all__ = [
    # Authentication
    "LoginRequest",
    "LogoutResponse",
    "PasswordChangeRequest",
    "RefreshTokenRequest",
    "RegisterRequest",
    "RegisterResponse",
    "TokenResponse",
    "UserResponse",
]