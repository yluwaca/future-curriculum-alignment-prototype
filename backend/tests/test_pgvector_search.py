"""Tests for pgvector-powered semantic search path."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_vector_status_returns_pgvector_flags(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/semantic/vector/status", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "pgvector_available" in payload
    assert "pgvector_installed" in payload
    assert "pgvector_column_present" in payload
    assert "active_storage_backend" in payload
    assert "sentence_transformers_available" in payload
    assert "active_embedding" in payload
    assert "pgvector" in payload["active_storage_backend"] or "jsonb" in payload["active_storage_backend"]


def test_semantic_search_returns_results_for_data_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/semantic/search",
        headers=auth_headers,
        json={"query": "data science machine learning", "top_k": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "query_id" in payload
    assert "model_key" in payload
    assert "result_count" in payload
    assert "results" in payload
    if payload["result_count"] > 0:
        result = payload["results"][0]
        assert "score" in result
        assert "content_preview" in result
        assert "chunk_id" in result


def test_semantic_search_empty_query_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/semantic/search",
        headers=auth_headers,
        json={"query": "", "top_k": 5},
    )
    assert response.status_code == 422, response.text


def test_semantic_search_with_min_score_filter(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/semantic/search",
        headers=auth_headers,
        json={"query": "python programming", "top_k": 5, "min_score": 0.5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    for result in payload.get("results", []):
        assert result["score"] >= 0.49, f"Score {result['score']} below min_score 0.5"


def test_semantic_search_top_k_respected(client: TestClient, auth_headers: dict[str, str]) -> None:
    for k in (1, 3, 10):
        response = client.post(
            "/api/v1/semantic/search",
            headers=auth_headers,
            json={"query": "database", "top_k": k},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["result_count"] <= k, f"top_k={k} returned {payload['result_count']} results"
