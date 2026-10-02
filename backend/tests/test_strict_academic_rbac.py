"""Regression tests for strict academic separation of duties."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.dependencies import require_role
from app.core import permissions as permission_module


def test_admin_flag_cannot_bypass_curriculum_approver_role():
    checker = require_role("CURRICULUM_APPROVER")
    admin = SimpleNamespace(is_admin=True, roles=[SimpleNamespace(role_id="admin")])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(checker(current_user=admin))
    assert exc.value.status_code == 403


def test_curriculum_approver_role_is_accepted_without_admin_flag():
    checker = require_role("CURRICULUM_APPROVER")
    approver = SimpleNamespace(
        is_admin=False, roles=[SimpleNamespace(role_id="curriculum_approver")]
    )
    assert asyncio.run(checker(current_user=approver)) is approver


def test_admin_flag_cannot_bypass_academic_permission(monkeypatch):
    monkeypatch.setattr(permission_module, "user_has_permission", lambda **_: False)
    monkeypatch.setattr(permission_module, "log_access_denied", lambda **_: None)
    checker = permission_module.require_permission("recommendation.academic_approve")
    request = SimpleNamespace(url=SimpleNamespace(path="/recommendations/x/approve"), method="POST")
    admin = SimpleNamespace(identity_id="admin-user", is_admin=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(checker(request=request, current_user=admin, db=SimpleNamespace()))
    assert exc.value.status_code == 403


def test_migration_maps_academic_permission_exclusively():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "release9a_curriculum_approver_rbac.py"
    ).read_text(encoding="utf-8")
    assert "DELETE FROM sec04_rolepermission" in migration
    assert "VALUES ('curriculum_approver', 'recommendation.academic_approve', true)" in migration
    assert "('admin', 'recommendation.academic_approve'" not in migration
    assert "('analyst', 'recommendation.academic_approve'" not in migration
    assert "('data_scientist', 'recommendation.academic_approve'" not in migration
