"""
Unit tests for Pydantic schema validation.
Tests request/response schemas for auth, admin, and user modules.
"""

import pytest
from pydantic import ValidationError


class TestLoginRequest:
    """Tests for LoginRequest schema."""

    def test_valid_login(self):
        from app.schemas.auth import LoginRequest
        req = LoginRequest(identifier="testuser", password="Password123!")
        assert req.identifier == "testuser"
        assert req.password == "Password123!"

    def test_identifier_normalized_lowercase(self):
        from app.schemas.auth import LoginRequest
        req = LoginRequest(identifier="  TestUser  ", password="Password123!")
        assert req.identifier == "testuser"

    def test_identifier_stripped(self):
        from app.schemas.auth import LoginRequest
        req = LoginRequest(identifier="  admin  ", password="Password123!")
        assert req.identifier == "admin"

    def test_empty_identifier_rejected(self):
        from app.schemas.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(identifier="", password="Password123!")

    def test_short_password_rejected(self):
        from app.schemas.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(identifier="user", password="short")

    def test_long_identifier_rejected(self):
        from app.schemas.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(identifier="a" * 200, password="Password123!")

    def test_extra_fields_rejected(self):
        from app.schemas.auth import LoginRequest
        with pytest.raises(ValidationError):
            LoginRequest(identifier="user", password="Password123!", extra="field")


class TestRegisterRequest:
    """Tests for RegisterRequest schema."""

    def test_valid_register(self):
        from app.schemas.auth import RegisterRequest
        req = RegisterRequest(
            username="newuser",
            email="user@example.com",
            password="SecurePass1!",
        )
        assert req.username == "newuser"
        assert req.email == "user@example.com"

    def test_username_normalized_lowercase(self):
        from app.schemas.auth import RegisterRequest
        req = RegisterRequest(
            username="  NewUser  ",
            email="user@example.com",
            password="SecurePass1!",
        )
        assert req.username == "newuser"

    def test_invalid_username_characters(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="user@name!",
                email="user@example.com",
                password="SecurePass1!",
            )

    def test_short_username_rejected(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="ab",
                email="user@example.com",
                password="SecurePass1!",
            )

    def test_invalid_email_rejected(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="not-an-email",
                password="SecurePass1!",
            )

    def test_weak_password_no_uppercase(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="user@example.com",
                password="nouppercase1!",
            )

    def test_weak_password_no_digit(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="user@example.com",
                password="NoDigitHere!",
            )

    def test_weak_password_no_lowercase(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="user@example.com",
                password="NOLOWERCASE1!",
            )

    def test_weak_password_too_short(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="user@example.com",
                password="Ab1!",
            )

    def test_extra_fields_rejected(self):
        from app.schemas.auth import RegisterRequest
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                email="user@example.com",
                password="SecurePass1!",
                role="admin",
            )


class TestRefreshTokenRequest:
    """Tests for RefreshTokenRequest schema."""

    def test_valid_refresh(self):
        from app.schemas.auth import RefreshTokenRequest
        req = RefreshTokenRequest(refresh_token="a" * 50)
        assert req.refresh_token == "a" * 50

    def test_short_token_rejected(self):
        from app.schemas.auth import RefreshTokenRequest
        with pytest.raises(ValidationError):
            RefreshTokenRequest(refresh_token="short")


class TestUserResponse:
    """Tests for UserResponse schema."""

    def test_user_response_with_roles(self):
        from app.schemas.auth import UserResponse
        resp = UserResponse(
            identity_id="testuser",
            email="test@example.com",
            identity_type="system",
            status="active",
            is_active=True,
            is_admin=False,
            approval_status="approved",
            roles=["Administrator", "Analyst"],
        )
        assert resp.roles == ["Administrator", "Analyst"]

    def test_user_response_default_roles_empty(self):
        from app.schemas.auth import UserResponse
        resp = UserResponse(
            identity_id="testuser",
            email="test@example.com",
            identity_type="system",
            status="active",
            is_active=True,
            is_admin=False,
        )
        assert resp.roles == []


class TestTokenResponse:
    """Tests for TokenResponse schema."""

    def test_valid_token_response(self):
        from app.schemas.auth import TokenResponse
        resp = TokenResponse(
            access_token="abc123",
            refresh_token="def456",
            token_type="bearer",
            expires_in=1800,
        )
        assert resp.access_token == "abc123"
        assert resp.expires_in == 1800

    def test_default_token_type(self):
        from app.schemas.auth import TokenResponse
        resp = TokenResponse(
            access_token="abc",
            expires_in=1800,
        )
        assert resp.token_type == "bearer"
