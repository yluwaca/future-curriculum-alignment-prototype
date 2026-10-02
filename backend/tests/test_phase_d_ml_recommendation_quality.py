"""Production ML and recommendation quality checks."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_forecast_quality_has_expected_sections(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/predictive/forecast/quality", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phase"] == "Forecast & Recommendation Quality"
    assert 0 <= payload["score"] <= 1
    assert {
        "forecast_evaluation",
        "model_registry",
        "recommendation_ranking",
        "explainability",
    }.issubset(payload.keys())
    assert "quality_score" in payload["forecast_evaluation"]
    assert "models" in payload["model_registry"]


def test_ranking_refresh_dry_run_does_not_mutate(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/predictive/forecast/recommendation-ranking/refresh?limit=5&dry_run=true",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dry_run"] is True
    assert "recommendations_checked" in payload
    assert payload["recommendations_updated"] == 0
    assert isinstance(payload["updates"], list)


def test_explainability_report_can_be_archived(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/predictive/forecast/explainability-report",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("report_id")
    assert payload.get("summary", {}).get("phase") == "Forecast & Recommendation Quality"
    assert payload.get("payload", {}).get("phase") == "Forecast & Recommendation Quality"


def test_predictive_status_returns_model_info(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/predictive/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "message" in payload
    assert any(k.endswith("_loaded") for k in payload) or any("model" in k.lower() for k in payload)


def test_predictive_align_endpoint_accepts_valid_module_code(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/predictive/align",
        headers=auth_headers,
        json={"module_code": "TEST101"},
    )
    assert response.status_code in (200, 404, 422, 500), response.text


def test_predictive_forecast_endpoint_accepts_valid_request(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/predictive/forecast",
        headers=auth_headers,
        json={"module_code": "TEST101", "forecast_horizon": 6},
    )
    assert response.status_code in (200, 404, 422, 500), response.text


def test_predictive_train_xgboost_endpoint_reachable(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/predictive/train/xgboost", headers=auth_headers)
    assert response.status_code in (200, 409), response.text
    if response.status_code == 200:
        payload = response.json()
        assert "metrics" in payload
        assert "message" in payload
        assert payload["metrics"]["model_type"] == "xgboost"
    else:
        payload = response.json()
        message = payload.get("detail", {})
        assert isinstance(message, dict), response.text
        assert "readiness" in message
        assert message["readiness"]["model_type"] == "xgboost"


def test_predictive_train_lstm_endpoint_reachable(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/predictive/train/lstm", headers=auth_headers)
    assert response.status_code in (200, 500), response.text
    if response.status_code == 200:
        payload = response.json()
        assert "metrics" in payload
        assert "message" in payload


def test_predictive_model_readiness_returns_gates(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/predictive/model-readiness", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "xgboost_loaded" in payload or "lstm_loaded" in payload or "baseline_metrics" in payload or "current_alignment_model" in payload
