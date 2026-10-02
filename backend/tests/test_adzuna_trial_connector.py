"""Adzuna live-trial connector and portal endpoint tests (DB-free)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.services.ingestion.job_board_api_connector import job_board_api_connector


def test_adzuna_profile_and_nested_mapping_are_explicitly_trial_only():
    profile = job_board_api_connector.provider_profile("adzuna")
    assert profile["source_key"] == "adzuna_jobs_api_trial"
    assert profile["job_id_prefix"] == "ADZUNA-TRIAL-"
    assert "academic research permission" in profile["name"]
    row = job_board_api_connector.to_job_advert_row(profile, {
        "id": "123", "title": "Data Analyst", "description": "SQL and Python",
        "created": "2026-09-08T00:00:00Z", "redirect_url": "https://example.invalid/job",
        "location": {"display_name": "Cape Town, Western Cape"},
        "company": {"display_name": "Example"}, "category": {"label": "IT Jobs"},
    })
    assert row["job_id"] == "ADZUNA-TRIAL-123"
    assert row["region"] == "Cape Town, Western Cape"
    assert row["company"] == "Example"
    assert row["skills"] is None


def test_category_label_is_never_promoted_to_a_skill():
    profile = job_board_api_connector.provider_profile("adzuna")
    payload = {
        "id": "456", "title": "Python Developer", "description": "Python, SQL and AWS",
        "created": "2026-09-08T00:00:00Z",
        "location": {"display_name": "Johannesburg, Gauteng"},
        "company": {"display_name": "Example"},
        "category": {"label": "Python", "tag": "python"},
        "category_tag": "python",
    }
    row = job_board_api_connector.to_job_advert_row(profile, payload)
    assert row["skills"] is None
    assert row["job_id"] == "ADZUNA-TRIAL-456"
    assert row["description"] == "Python, SQL and AWS"


def test_trial_label_applies_to_every_row():
    profile = job_board_api_connector.provider_profile("adzuna")
    rows = []
    for index in range(2):
        rows.append(job_board_api_connector.to_job_advert_row(profile, {
            "id": str(index), "title": "Job", "created": "2026-09-08T00:00:00Z",
            "location": {"display_name": "Cape Town"}, "company": {"display_name": "Co"},
        }))
    assert [row["job_id"] for row in rows] == ["ADZUNA-TRIAL-0", "ADZUNA-TRIAL-1"]


def test_optional_fields_are_null_safe():
    profile = job_board_api_connector.provider_profile("adzuna")
    row = job_board_api_connector.to_job_advert_row(profile, {
        "id": "789", "title": "Role", "description": "desc", "created": "2026-09-08T00:00:00Z",
        "location": "Cape Town, Western Cape",
    })
    assert row["posted_date"] == "2026-09-08T00:00:00Z"
    assert row["source_url"] is None
    assert row["company"] is None


class _FakeQuery:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._filters = []

    def filter(self, *args, **kwargs):
        self._filters.append(args or kwargs)
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def offset(self, n):
        return self

    def count(self):
        return len(self._rows)

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, source_rows=None, postings=None, job=None):
        self._source_rows = source_rows or []
        self._postings = postings or []
        self._job = job

    def query(self, *models):
        if JobPosting in models:
            return _FakeQuery(self._postings)
        if DataSource in models:
            return _FakeQuery(self._source_rows)
        return _FakeQuery([])

    def get(self, model, pk):
        return self._job

    def add(self, *args, **kwargs):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


@pytest.fixture()
def fake_user():
    u = SimpleNamespace()
    u.identity_id = "uat-analyst-001"
    u.identity_type = "user"
    u.primary_role_name = "ANALYST"
    u.is_admin = True
    return u


@pytest.fixture()
def authed_client(fake_user):
    app.dependency_overrides[get_current_user] = lambda: fake_user
    with TestClient(app) as client:
        yield client, fake_user
    app.dependency_overrides.clear()


def _source():
    s = SimpleNamespace()
    s.source_id = uuid4()
    s.source_key = "adzuna_jobs_api_trial"
    s.name = "Adzuna Jobs API (academic research permission)"
    s.auth_config = None
    return s


def _posting(job_uuid, index):
    p = SimpleNamespace()
    p.posting_id = uuid4()
    p.job_id = f"ADZUNA-TRIAL-{index}"
    p.job_title = "Software Developer"
    p.region = "Cape Town, Western Cape"
    p.posted_date = "2026-09-08T00:00:00Z"
    p.job_description = "Build software with Python."
    p.source_url = "https://example.invalid/jobs/1"
    p.ingestion_job_id = job_uuid
    return p, _source()


def test_limit_bounds_rejected(authed_client):
    client, _ = authed_client
    assert client.post("/api/v1/ingestion/adzuna/import", json={
        "what": "x", "where": "Cape Town", "limit": 0}).status_code == 422
    assert client.post("/api/v1/ingestion/adzuna/import", json={
        "what": "x", "where": "Cape Town", "limit": 51}).status_code == 422
    assert client.post("/api/v1/ingestion/adzuna/import", json={
        "what": "", "where": "Cape Town", "limit": 5}).status_code == 422


def test_import_missing_credentials_is_503(authed_client, monkeypatch):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB(source_rows=[])
    try:
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        response = client.post("/api/v1/ingestion/adzuna/import", json={
            "what": "developer", "where": "Cape Town", "limit": 5})
        assert response.status_code == 503
        assert "credentials" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_import_provider_unreachable_is_502(authed_client, monkeypatch):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB(source_rows=[_source()])

    def _boom(*args, **kwargs):
        raise requests.RequestException("connection refused")

    try:
        monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "test-app-key")
        monkeypatch.setattr("app.routers.ingestion.requests.get", _boom)
        response = client.post("/api/v1/ingestion/adzuna/import", json={
            "what": "developer", "where": "Cape Town", "limit": 5})
        assert response.status_code == 502
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_import_provider_error_status_is_502(authed_client, monkeypatch):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB(source_rows=[_source()])

    class _Resp:
        status_code = 429

    try:
        monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "test-app-key")
        monkeypatch.setattr("app.routers.ingestion.requests.get", lambda *a, **k: _Resp())
        response = client.post("/api/v1/ingestion/adzuna/import", json={
            "what": "developer", "where": "Cape Town", "limit": 5})
        assert response.status_code == 502
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_import_unexpected_format_is_502(authed_client, monkeypatch):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB(source_rows=[_source()])
    positive = type("_Ok", (), {"status_code": 200})()
    positive.json = lambda: {"count": 0}

    try:
        monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "test-app-key")
        monkeypatch.setattr("app.routers.ingestion.requests.get", lambda *a, **k: positive)
        response = client.post("/api/v1/ingestion/adzuna/import", json={
            "what": "developer", "where": "Cape Town", "limit": 5})
        assert response.status_code == 502
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_import_success_passes_trial_metadata(authed_client, monkeypatch):
    client, _ = authed_client
    job_uuid = uuid4()
    job = SimpleNamespace(parameters={})
    fake_db = _FakeDB(source_rows=[_source()], job=job)
    app.dependency_overrides[get_db] = lambda: fake_db
    captured = {}
    positive = type("_Ok", (), {"status_code": 200})()
    positive.json = lambda: {"results": [{"id": str(i), "title": "t", "created": "2"}
                                         for i in range(7)]}

    def _fake_ingest(db, provider, rows, actor_id, **kwargs):
        captured["rows"] = rows
        captured["provider"] = provider
        captured["actor_id"] = actor_id
        captured["kwargs"] = kwargs
        return {
            "job_id": str(job_uuid), "source_id": str(uuid4()), "provider": "adzuna",
            "records_seen": len(rows), "inserted": len(rows),
            "updated": 0, "failed": 0,
        }

    try:
        monkeypatch.setenv("ADZUNA_APP_ID", "test-app-id")
        monkeypatch.setenv("ADZUNA_APP_KEY", "test-app-key")
        monkeypatch.setattr("app.routers.ingestion.requests.get", lambda *a, **k: positive)
        monkeypatch.setattr(
            "app.routers.ingestion.job_board_api_connector.ingest_payloads", _fake_ingest)
        response = client.post("/api/v1/ingestion/adzuna/import", json={
            "what": "software developer", "where": "Cape Town", "limit": 5})
        assert response.status_code == 200
        body = response.json()
        assert body["records_seen"] == 5
        assert len(captured["rows"]) == 5
        assert captured["kwargs"]["acquisition_mode"] == "live_trial_uat"
        assert captured["kwargs"]["source_label"] == "ADZUNA_TRIAL_NOT_EMPIRICAL"
        assert job.parameters["initiated_via"] == "portal"
        assert job.parameters["query"]["what"] == "software developer"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_posts_returns_source_name_not_orm(authed_client, monkeypatch):
    client, _ = authed_client
    job_uuid = uuid4()
    app.dependency_overrides[get_db] = lambda: _FakeDB(postings=[_posting(job_uuid, 1)])
    monkeypatch.setattr("app.routers.ingestion.scope_query", lambda q, m, u, **k: q)
    try:
        response = client.get("/api/v1/ingestion/adzuna/posts")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["job_id"] == "ADZUNA-TRIAL-1"
        assert items[0]["source"] == "Adzuna Jobs API (academic research permission)"
        assert "auth_config" not in items[0]
    finally:
        app.dependency_overrides.pop(get_db, None)