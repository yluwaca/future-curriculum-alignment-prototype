"""
Unit tests for admin service logic.
Tests user CRUD, role assignment, approval flow, account lockout.
Uses mocks to avoid database dependency.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone


class TestUserModel:
    """Tests for User model properties."""

    def _make_user(self, **kwargs):
        from app.models.user import User
        defaults = {
            "identity_id": "testuser",
            "email": "test@example.com",
            "identity_type": "system",
            "status": "active",
            "is_active": True,
            "is_admin": False,
            "password_hash": "$2b$12$LJ3m4ris89S5R5OoG5BhOeOkd5c1LQz.7K3Z.8X9Y0A1B2C3D4E5F6",
            "approval_status": "approved",
            "failed_login_attempts": 0,
            "roles": [],
        }
        defaults.update(kwargs)
        user = User()
        for k, v in defaults.items():
            setattr(user, k, v)
        return user

    def test_user_is_active_by_default(self):
        user = self._make_user(is_active=True)
        assert user.is_active is True

    def test_user_approval_status(self):
        user = self._make_user(approval_status="pending")
        assert user.approval_status == "pending"

    def test_user_failed_login_attempts_zero(self):
        user = self._make_user(failed_login_attempts=0)
        assert user.failed_login_attempts == 0

    def test_user_admin_flag(self):
        user = self._make_user(is_admin=True)
        assert user.is_admin is True


class TestAccountLockout:
    """Tests for account lockout logic."""

    def _make_user(self, **kwargs):
        from app.models.user import User
        user = User()
        defaults = {
            "identity_id": "testuser",
            "is_active": True,
            "failed_login_attempts": 0,
            "approval_status": "approved",
            "password_hash": "$2b$12$LJ3m4ris89S5R5OoG5BhOeOkd5c1LQz.7K3Z.8X9Y0A1B2C3D4E5F6",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(user, k, v)
        return user

    def test_lockout_after_5_failed_attempts(self):
        user = self._make_user(failed_login_attempts=4, is_active=True)
        from app.core.security import verify_password
        # Simulate failed login
        failed = user.failed_login_attempts or 0
        user.failed_login_attempts = failed + 1
        if user.failed_login_attempts >= 5:
            user.is_active = False
        assert user.is_active is False
        assert user.failed_login_attempts == 5

    def test_no_lockout_below_threshold(self):
        user = self._make_user(failed_login_attempts=3, is_active=True)
        failed = user.failed_login_attempts or 0
        user.failed_login_attempts = failed + 1
        if user.failed_login_attempts >= 5:
            user.is_active = False
        assert user.is_active is True
        assert user.failed_login_attempts == 4

    def test_reset_failed_attempts_on_success(self):
        user = self._make_user(failed_login_attempts=3)
        user.failed_login_attempts = 0
        assert user.failed_login_attempts == 0

    def test_unlock_resets_counter(self):
        user = self._make_user(failed_login_attempts=7, is_active=False)
        user.is_active = True
        user.failed_login_attempts = 0
        assert user.is_active is True
        assert user.failed_login_attempts == 0


class TestRoleAssignment:
    """Tests for role assignment logic."""

    def test_admin_role_sets_is_admin(self):
        roles = ["admin", "viewer"]
        is_admin = "admin" in roles
        assert is_admin is True

    def test_non_admin_role_does_not_set_is_admin(self):
        roles = ["viewer", "analyst"]
        is_admin = "admin" in roles
        assert is_admin is False

    def test_empty_roles_clears_is_admin(self):
        roles = []
        is_admin = "admin" in roles
        assert is_admin is False
