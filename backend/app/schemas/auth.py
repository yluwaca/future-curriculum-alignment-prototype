# backend/app/schemas/auth.py

"""
Authentication schemas.

Supports:

- Registration
- Login
- Token refresh
- Password changes
- Session-aware authentication
- User profile retrieval
"""

from typing import Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# =========================================================
# Password Validation
# =========================================================


def validate_password_complexity(
    password: str,
) -> str:
    """
    Password complexity validation.

    Requirements:
    - minimum 8 characters
    - uppercase
    - lowercase
    - numeric
    """

    if len(password) < 8:

        raise ValueError(
            "Password must be at least 8 characters"
        )

    has_upper = any(
        char.isupper()
        for char in password
    )

    has_lower = any(
        char.islower()
        for char in password
    )

    has_digit = any(
        char.isdigit()
        for char in password
    )

    if not (
        has_upper
        and has_lower
        and has_digit
    ):

        raise ValueError(
            (
                "Password must contain "
                "uppercase, lowercase "
                "and numeric characters"
            )
        )

    return password


# =========================================================
# Login Request
# =========================================================


class LoginRequest(BaseModel):
    """
    Login request.
    """

    identifier: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description=(
            "Username or identity ID"
        ),
    )

    password: str = Field(
        ...,
        min_length=8,
        max_length=256,
        description="User password",
    )

    @field_validator(
        "identifier",
        mode="before",
    )
    @classmethod
    def normalize_identifier(
        cls,
        value: str,
    ) -> str:

        return value.strip().lower()

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Register Request
# =========================================================


class RegisterRequest(BaseModel):
    """
    Registration request.
    """

    username: str = Field(
        ...,
        min_length=3,
        max_length=100,
        pattern=r"^[a-zA-Z0-9._-]+$",
        description="Unique username",
    )

    email: EmailStr

    password: str = Field(
        ...,
        min_length=8,
        max_length=256,
    )

    @field_validator(
        "username",
        mode="before",
    )
    @classmethod
    def normalize_username(
        cls,
        value: str,
    ) -> str:

        return value.strip().lower()

    @field_validator(
        "email",
        mode="before",
    )
    @classmethod
    def normalize_email(
        cls,
        value: str,
    ) -> str:

        return value.strip().lower()

    @field_validator(
        "password"
    )
    @classmethod
    def validate_password(
        cls,
        value: str,
    ) -> str:

        return validate_password_complexity(
            value
        )

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Registration Response
# =========================================================


class RegisterResponse(BaseModel):
    """
    Registration response.
    """

    message: str

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Refresh Request
# =========================================================


class RefreshTokenRequest(BaseModel):
    """
    Refresh token request.
    """

    refresh_token: str = Field(
        ...,
        min_length=20,
        max_length=5000,
        description="Refresh token",
    )

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Token Response
# =========================================================


class TokenResponse(BaseModel):
    """
    Authentication response.

    Access Token:
        Stateless JWT

    Refresh Token:
        Stateful session-backed token
    """

    access_token: str

    refresh_token: Optional[str] = None

    token_type: str = "bearer"

    expires_in: int

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Logout Response
# =========================================================


class LogoutResponse(BaseModel):
    """
    Logout response.
    """

    message: str

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# Password Change Request
# =========================================================


class PasswordChangeRequest(BaseModel):
    """
    Password change request.
    """

    current_password: str

    new_password: str

    confirm_new_password: str

    @field_validator(
        "new_password"
    )
    @classmethod
    def validate_password(
        cls,
        value: str,
    ) -> str:

        return validate_password_complexity(
            value
        )

    @model_validator(
        mode="after"
    )
    def passwords_match(self):

        if (
            self.new_password
            != self.confirm_new_password
        ):

            raise ValueError(
                (
                    "New password and "
                    "confirmation do not match"
                )
            )

        return self

    model_config = ConfigDict(
        extra="forbid",
    )


# =========================================================
# User Response
# =========================================================


class UserResponse(BaseModel):
    """
    Authenticated user response.
    """

    identity_id: str

    tenant_id: Optional[UUID] = None

    email: Optional[str] = None

    identity_type: str

    status: str

    is_active: bool

    is_admin: bool

    approval_status: str = "pending"

    roles: list[str] = []

    model_config = ConfigDict(
        from_attributes=True,
    )

