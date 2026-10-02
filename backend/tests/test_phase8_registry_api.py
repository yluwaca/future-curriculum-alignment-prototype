"""
Phase 8: Registry API endpoint tests.

Tests the /predictive/registry endpoints for model lifecycle management.
Uses FastAPI dependency_overrides to mock auth without a live DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.dependencies import get_current_user


@pytest.fixture()
def fake_user():
    u = MagicMock()
    u.identity_id = "test-user-001"
    u.primary_role_name = "ADMIN"
    u.is_admin = True
    return u


@pytest.fixture()
def authed_client(fake_user):
    """TestClient with auth dependency overridden."""
    app.dependency_overrides[get_current_user] = lambda: fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


REGISTRY_ENDPOINTS = [
    ("list_registry", "GET", "/api/v1/predictive/registry"),
    ("active_xgboost", "GET", "/api/v1/predictive/registry/active/xgboost"),
    ("active_lstm", "GET", "/api/v1/predictive/registry/active/lstm"),
]


def test_registry_endpoints_require_auth(client: TestClient) -> None:
    """Registry endpoints should reject unauthenticated requests."""
    for name, method, path in REGISTRY_ENDPOINTS:
        response = client.request(method, path)
        assert response.status_code in (401, 403), (
            f"{name} should require auth, got {response.status_code}"
        )


def test_registry_list_endpoint(authed_client: TestClient) -> None:
    """Registry list endpoint should return a list structure."""
    response = authed_client.get("/api/v1/predictive/registry")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "entries" in data
    assert "count" in data
    assert isinstance(data["entries"], list)


def test_registry_active_model_not_found(authed_client: TestClient) -> None:
    """Active model endpoint should return 404 when no active model exists."""
    response = authed_client.get("/api/v1/predictive/registry/active/nonexistent_model_type")
    assert response.status_code == 404


def test_registry_get_entry_invalid_id(authed_client: TestClient) -> None:
    """Getting a registry entry with invalid UUID should return 400."""
    response = authed_client.get("/api/v1/predictive/registry/not-a-valid-uuid")
    assert response.status_code == 400


def test_registry_promote_invalid_id(authed_client: TestClient) -> None:
    """Promoting with invalid UUID should return 400."""
    response = authed_client.post("/api/v1/predictive/registry/not-a-valid-uuid/promote")
    assert response.status_code == 400


def test_registry_gates_invalid_id(authed_client: TestClient) -> None:
    """Checking gates with invalid UUID should return 400."""
    response = authed_client.post("/api/v1/predictive/registry/not-a-valid-uuid/gates")
    assert response.status_code == 400


def test_registry_reject_invalid_id(authed_client: TestClient) -> None:
    """Rejecting with invalid UUID should return 400."""
    response = authed_client.post("/api/v1/predictive/registry/not-a-valid-uuid/reject")
    assert response.status_code == 400


def test_registry_rollback_invalid_type(authed_client: TestClient) -> None:
    """Rollback for non-existent type should return 404."""
    response = authed_client.post("/api/v1/predictive/registry/rollback/nonexistent_model_type")
    assert response.status_code == 404
