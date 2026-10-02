"""Production security and operations readiness checks."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_security_readiness_has_expected_sections(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/operations/security-readiness", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phase"] == "Security & Operations Readiness"
    assert 0 <= payload["score"] <= 1
    assert {
        "rbac_tenant_hardening",
        "credential_security",
        "scheduler",
        "monitoring",
        "backups",
    }.issubset(payload.keys())
    assert "quality_score" in payload["credential_security"]


def test_operations_monitoring_scheduler_and_backup_summaries(client: TestClient, auth_headers: dict[str, str]) -> None:
    for path in ("/api/v1/operations/monitoring", "/api/v1/operations/scheduler", "/api/v1/operations/backups"):
        response = client.get(path, headers=auth_headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert "quality_score" in payload
        assert "issues" in payload


def test_backup_manifest_can_be_archived(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/operations/backups/manifest", headers=auth_headers, json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("report_id")
    assert payload.get("payload_hash")
    assert payload.get("manifest_path", "").endswith(".json")
    assert payload.get("payload", {}).get("backup_mode") == "manifest_only_local_readiness"
