from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.monitoring_alert_service import MonitoringAlertService


ROOT = Path(__file__).resolve().parents[1]


def test_alert_serialisation_exposes_lifecycle_and_delivery_evidence():
    tenant_id = uuid4()
    alert_id = uuid4()
    alert = SimpleNamespace(
        alert_id=alert_id,
        tenant_id=tenant_id,
        alert_key="worker.stopped",
        component="worker",
        severity="critical",
        status="open",
        title="Worker stopped",
        message="Jobs cannot execute",
        evidence={"status": "stopped"},
        occurrence_count=2,
        first_detected_at=None,
        last_detected_at=None,
        acknowledged_at=None,
        acknowledged_by=None,
        acknowledgement_note=None,
        resolved_at=None,
        notification_status="delivered",
        notification_attempts=1,
        last_notification_at=None,
        notification_error=None,
    )
    payload = MonitoringAlertService.serialise(alert)
    assert payload["alert_id"] == str(alert_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["notification_status"] == "delivered"
    assert payload["occurrence_count"] == 2


def test_monitoring_routes_are_admin_only_and_tenant_bound():
    source = (ROOT / "app/routers/operations.py").read_text(encoding="utf-8")
    assert '@router.post("/monitoring/evaluate")' in source
    assert '@router.get("/alerts")' in source
    assert '@router.post("/alerts/{alert_id}/acknowledge")' in source
    assert source.count('Depends(require_role("ADMIN"))') >= 8
    assert "current_user.tenant_id" in source


def test_monitoring_evaluator_covers_required_operational_components():
    source = (ROOT / "app/services/monitoring_alert_service.py").read_text(encoding="utf-8")
    for rule in (
        "worker.stopped",
        "operational_jobs.failed_24h",
        "ingestion.failure_rate",
        "sources.degraded",
        "backup.missing",
        "backup.unverified",
    ):
        assert rule in source
    assert 'os.getenv("FUTURE_ALERT_WEBHOOK_URL"' in source
    assert '"prometheus_endpoint": "/metrics"' in source


def test_alert_migration_and_portal_controls_exist():
    migration = (
        ROOT / "migrations/versions/release5_external_monitoring_alerts.py"
    ).read_text(encoding="utf-8")
    portal = (ROOT.parent / "frontend/system-operations.html").read_text(encoding="utf-8")
    assert 'op.create_table(\n        "system_alert"' in migration
    assert "acknowledged_by" in migration
    assert "notification_status" in migration
    assert 'id="evaluateMonitoringBtn"' in portal
    assert 'id="systemAlertRows"' in portal
