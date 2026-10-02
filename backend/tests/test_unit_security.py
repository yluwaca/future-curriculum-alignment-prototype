"""
Unit tests for security utilities.
Password hashing, JWT tokens, session IDs.
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password_returns_string(self):
        from app.core.security import hash_password
        result = hash_password("TestPassword123!")
        assert isinstance(result, str)

    def test_hash_password_is_bcrypt(self):
        from app.core.security import hash_password
        result = hash_password("TestPassword123!")
        assert result.startswith("$2b$") or result.startswith("$2a$")

    def test_verify_password_correct(self):
        from app.core.security import hash_password, verify_password
        password = "MySecurePass1!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        from app.core.security import hash_password, verify_password
        hashed = hash_password("CorrectPassword1!")
        assert verify_password("WrongPassword1!", hashed) is False

    def test_different_hashes_for_same_password(self):
        from app.core.security import hash_password
        h1 = hash_password("SamePassword1!")
        h2 = hash_password("SamePassword1!")
        assert h1 != h2

    def test_hash_empty_password(self):
        from app.core.security import hash_password
        result = hash_password("")
        assert isinstance(result, str)

    def test_hash_long_password(self):
        from app.core.security import hash_password
        long_pass = "A" * 256 + "1a"
        result = hash_password(long_pass)
        assert isinstance(result, str)


class TestSessionId:
    """Tests for session ID generation."""

    def test_create_session_id_returns_uuid(self):
        from app.core.security import create_session_id
        sid = create_session_id()
        assert isinstance(sid, str)
        parts = sid.split("-")
        assert len(parts) == 5

    def test_session_ids_are_unique(self):
        from app.core.security import create_session_id
        ids = {create_session_id() for _ in range(100)}
        assert len(ids) == 100


class TestJWTTokenCreation:
    """Tests for JWT access and refresh token creation."""

    def test_create_access_token_returns_string(self):
        from app.core.security import create_access_token
        token = create_access_token({"sub": "testuser"}, session_id="test-session-id")
        assert isinstance(token, str)
        assert len(token) > 50

    def test_create_refresh_token_returns_string(self):
        from app.core.security import create_refresh_token
        token = create_refresh_token("testuser", session_id="test-session-id")
        assert isinstance(token, str)
        assert len(token) > 50

    def test_access_token_contains_sub(self):
        from app.core.security import create_access_token, verify_token
        token = create_access_token({"sub": "alice"}, session_id="sess-1")
        payload = verify_token(token, expected_type="access")
        assert payload["sub"] == "alice"

    def test_refresh_token_contains_sub(self):
        from app.core.security import create_refresh_token, verify_token
        token = create_refresh_token("bob", session_id="sess-2")
        payload = verify_token(token, expected_type="refresh")
        assert payload["sub"] == "bob"

    def test_access_and_refresh_use_same_session_id(self):
        from app.core.security import create_access_token, create_refresh_token, verify_token
        sid = "shared-session-id"
        access = create_access_token({"sub": "user1"}, session_id=sid)
        refresh = create_refresh_token("user1", session_id=sid)
        ap = verify_token(access, expected_type="access")
        rp = verify_token(refresh, expected_type="refresh")
        assert ap["jti"] == rp["jti"] == sid

    def test_access_token_type(self):
        from app.core.security import create_access_token, verify_token
        token = create_access_token({"sub": "u"}, session_id="s1")
        p = verify_token(token)
        assert p["type"] == "access"

    def test_refresh_token_type(self):
        from app.core.security import create_refresh_token, verify_token
        token = create_refresh_token("u", session_id="s1")
        p = verify_token(token)
        assert p["type"] == "refresh"


class TestJWTTokenVerification:
    """Tests for JWT token verification and rejection."""

    def test_verify_valid_token(self):
        from app.core.security import create_access_token, verify_token
        token = create_access_token({"sub": "user"}, session_id="s1")
        payload = verify_token(token, expected_type="access")
        assert payload["sub"] == "user"

    def test_reject_wrong_type(self):
        from app.core.security import create_access_token, verify_token
        from fastapi import HTTPException
        token = create_access_token({"sub": "user"}, session_id="s1")
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, expected_type="refresh")
        assert exc_info.value.status_code == 401

    def test_reject_tampered_token(self):
        from app.core.security import create_access_token, verify_token
        from fastapi import HTTPException
        token = create_access_token({"sub": "user"}, session_id="s1")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException):
            verify_token(tampered, expected_type="access")

    def test_reject_expired_token(self):
        from app.core.security import SECRET_KEY, ALGORITHM, JWT_AUDIENCE, JWT_ISSUER, verify_token
        from fastapi import HTTPException
        from jose import jwt as jose_jwt
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user",
            "jti": "old-session",
            "type": "access",
            "iat": now - timedelta(hours=2),
            "nbf": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
        }
        token = jose_jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token, expected_type="access")
        assert exc_info.value.status_code == 401


class TestTokenHashing:
    """Tests for token hashing utility."""

    def test_hash_token_deterministic(self):
        from app.core.security import hash_token
        token = "some.jwt.token.value"
        h1 = hash_token(token)
        h2 = hash_token(token)
        assert h1 == h2

    def test_hash_token_different_inputs(self):
        from app.core.security import hash_token
        assert hash_token("token-a") != hash_token("token-b")

    def test_hash_token_returns_hex(self):
        from app.core.security import hash_token
        h = hash_token("test-token")
        int(h, 16)  # Should not raise
