"""Authenticated backend/API smoke tests for the current production-readiness baseline."""

from __future__ import annotations

from fastapi.testclient import TestClient


SMOKE_ENDPOINTS = [
    ("health", "GET", "/health"),
    ("openapi", "GET", "/openapi.json"),
    ("current_user", "GET", "/api/v1/auth/me"),
    ("ingestion_readiness", "GET", "/api/v1/ingestion/readiness"),
    ("ingestion_sources", "GET", "/api/v1/ingestion/sources?limit=5"),
    ("ingestion_review_current_jobs", "GET", "/api/v1/ingestion/records/review?limit=2&source_category=current_jobs"),
    ("data_quality_summary", "GET", "/api/v1/ingestion/data-quality/summary"),
    ("skills_alignment_readiness", "GET", "/api/v1/skills/readiness"),
    ("alignment_calibration", "GET", "/api/v1/skills/alignment-calibration?limit=3"),
    ("processing_summary", "GET", "/api/v1/processing/summary"),
    ("model_readiness", "GET", "/api/v1/predictive/model-readiness"),
    ("forecast_quality", "GET", "/api/v1/predictive/forecast/quality"),
    ("security_operations_readiness", "GET", "/api/v1/operations/security-readiness"),
    ("deployment_readiness", "GET", "/api/v1/operations/deployment-readiness"),
    ("analytics_summary", "GET", "/api/v1/analytics/summary"),
    ("skill_gaps", "GET", "/api/v1/analytics/skill-gaps?limit=2"),
    ("recommendations_grouped", "GET", "/api/v1/analytics/recommendations/grouped?status=pending_review&limit=3"),
]


REQUIRED_OPENAPI_PATHS = [
    "/api/v1/ingestion/readiness",
    "/api/v1/ingestion/records/review",
    "/api/v1/ingestion/data-quality/summary",
    "/api/v1/ingestion/data-quality/remap-table-rows",
    "/api/v1/skills/readiness",
    "/api/v1/skills/alignment-calibration",
    "/api/v1/skills/alignment-calibration/{alignment_id}",
    "/api/v1/skills/semantic-candidates/{skill_id}",
    "/api/v1/processing/run/full",
    "/api/v1/analytics/skill-gaps",
    "/api/v1/analytics/skill-gaps/{skill_id}/evidence",
    "/api/v1/predictive/model-readiness",
    "/api/v1/predictive/forecast/quality",
    "/api/v1/predictive/forecast/recommendation-ranking/refresh",
    "/api/v1/predictive/forecast/explainability-report",
]


def test_openapi_contains_production_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json().get("paths", {})
    missing = [path for path in REQUIRED_OPENAPI_PATHS if path not in paths]
    assert not missing, f"Missing expected OpenAPI paths: {missing}"


def test_authenticated_smoke_endpoints(client: TestClient, auth_headers: dict[str, str]) -> None:
    for name, method, path in SMOKE_ENDPOINTS:
        headers = auth_headers if path.startswith("/api/") else None
        response = client.request(method, path, headers=headers)
        assert response.status_code == 200, f"{name} failed: {response.status_code} {response.text[:300]}"


def test_skill_gap_evidence_drilldown_returns_grouped_sources(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    gaps_response = client.get("/api/v1/analytics/skill-gaps?limit=1", headers=auth_headers)
    assert gaps_response.status_code == 200, gaps_response.text
    gaps = gaps_response.json().get("gaps") or []
    assert gaps, "No skill gaps returned; run analytics before production readiness validation"

    skill_id = gaps[0]["skill_id"]
    evidence_response = client.get(
        f"/api/v1/analytics/skill-gaps/{skill_id}/evidence?limit=2",
        headers=auth_headers,
    )
    assert evidence_response.status_code == 200, evidence_response.text
    payload = evidence_response.json()
    assert payload.get("found") is True
    assert payload.get("why_this_skill_matters")
    groups = payload.get("source_groups") or {}
    assert {"curriculum", "job_trends", "current_jobs"}.issubset(groups.keys())
    counts = payload.get("counts") or {}
    assert {"curriculum", "job_trends", "current_jobs"}.issubset(counts.keys())
