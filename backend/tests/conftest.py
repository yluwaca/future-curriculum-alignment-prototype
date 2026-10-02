"""Shared fixtures for production-readiness smoke tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.models.tenant import Tenant


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"


def ensure_test_login_user(identifier: str, password: str) -> None:
    """Create or repair the local smoke-test login user."""
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.tenant_key == "future_test").first()
        if tenant is None:
            tenant = Tenant(
                tenant_key="future_test",
                name="FUTURE Test Tenant",
                tenant_type="institution",
                country="South Africa",
                region="Western Cape",
                status="active",
                description="Local automated test tenant.",
            )
            db.add(tenant)
            db.flush()

        user = db.query(User).filter(User.identity_id == identifier).first()
        if user is None:
            user = User(
                identity_id=identifier,
                email=f"{identifier}@future-platform.local",
                password_hash=hash_password(password),
                identity_type="human",
                status="active",
                is_active=True,
                is_admin=True,
                approval_status="approved",
                tenant_id=tenant.tenant_id,
            )
            db.add(user)
        else:
            user.password_hash = hash_password(password)
            user.identity_type = user.identity_type or "human"
            user.status = "active"
            user.is_active = True
            user.is_admin = True
            user.approval_status = "approved"
            user.failed_login_attempts = 0
            user.locked_until = None
            user.tenant_id = tenant.tenant_id
        db.commit()
    finally:
        db.close()

@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def auth_headers(client: TestClient) -> Dict[str, str]:
    identifier = os.getenv("PCLMAS_TEST_USER", "testuser")
    password = os.getenv("PCLMAS_TEST_PASSWORD", "Test123!")
    ensure_test_login_user(identifier, password)
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": password},
    )
    assert response.status_code == 200, response.text
    token = response.json().get("access_token")
    assert token, "Login response did not include an access_token"
    return {"Authorization": f"Bearer {token}"}



