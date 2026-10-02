from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.tenant_scope import (
    assert_entity_access,
    enforce_requested_tenant,
    require_user_tenant,
)


def test_missing_tenant_fails_closed():
    with pytest.raises(HTTPException) as exc:
        require_user_tenant(SimpleNamespace(tenant_id=None))
    assert exc.value.status_code == 403


def test_requested_cross_tenant_context_is_hidden():
    user = SimpleNamespace(tenant_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        enforce_requested_tenant(user, uuid4())
    assert exc.value.status_code == 404


def test_cross_tenant_entity_is_hidden_but_shared_reference_is_allowed():
    own_tenant = uuid4()
    user = SimpleNamespace(tenant_id=own_tenant)
    assert assert_entity_access(SimpleNamespace(tenant_id=own_tenant), user) == own_tenant
    assert assert_entity_access(SimpleNamespace(tenant_id=None), user) == own_tenant
    with pytest.raises(HTTPException) as exc:
        assert_entity_access(SimpleNamespace(tenant_id=uuid4()), user)
    assert exc.value.status_code == 404


def test_tenant_identity_and_background_upload_are_wired_end_to_end():
    root = Path(__file__).resolve().parents[1]
    dependencies = (root / "app/core/dependencies.py").read_text(encoding="utf-8")
    curriculum = (root / "app/routers/curriculum.py").read_text(encoding="utf-8")
    worker = (root / "app/services/operational_job_service.py").read_text(encoding="utf-8")
    ingestion = (
        root / "app/services/ingestion/curriculum_pdf_service.py"
    ).read_text(encoding="utf-8")
    assert 'db.info["tenant_id"]' in dependencies
    assert '"tenant_id": str(current_user.tenant_id)' in curriculum
    assert 'tenant_id=p.get("tenant_id")' in worker
    assert "Tenant context is required for curriculum ingestion" in ingestion


def test_release5_migration_seeds_and_backfills_cput_tenant():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/release5_strict_tenant_identity.py"
    ).read_text(encoding="utf-8")
    assert "fk_identity_tenant_id" in migration
    assert "'cput'" in migration
    assert "UPDATE curriculum_document" in migration
    assert "UPDATE pipeline_run" in migration
