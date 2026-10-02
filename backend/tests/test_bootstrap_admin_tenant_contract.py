from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_admin_is_bound_to_active_cput_tenant() -> None:
    source = (ROOT / "app/core/bootstrap.py").read_text(encoding="utf-8")

    assert 'Tenant.tenant_key == "cput"' in source
    assert 'Tenant.status == "active"' in source
    assert "admin.tenant_id = default_tenant.tenant_id" in source
    assert "tenant_id=default_tenant.tenant_id" in source
    assert "apply migrations before admin bootstrap" in source
