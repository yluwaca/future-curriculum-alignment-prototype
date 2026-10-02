"""Bounded Adzuna pagination importer tests (DB-free).

Covers the full paginated import contract: page 1 + 2 retrieval, client-side
date filtering, provider-stable-id dedup, rerun idempotency, partial page
failure + retry, stopping on an empty page, rate-limit (HTTP 429) backoff,
abort after consecutive failures, audit metadata, and server-side bounds.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.services.ingestion.adzuna_paginated_importer import (
    DEFAULT_PAGE_RANGE,
    MAX_PAGES_PER_RUN,
    PAGE_NUMBER_MAX,
    PAGE_SIZE_MAX,
    adzuna_paginated_importer,
)


def _resp(body, status_code=200, headers=None):
    r = SimpleNamespace(status_code=status_code, headers=headers or {})
    r.json = lambda body=body: body
    return r


def _adzuna_row(ad_id, created, title="Software Developer"):
    return {
        "id": str(ad_id),
        "title": title,
        "description": f"Build software for account {ad_id}.",
        "created": created,
        "redirect_url": f"https://www.adzuna.co.za/jobs/{ad_id}",
        "location": {"display_name": "Cape Town, Western Cape", "area": ["Cape Town"]},
        "company": {"display_name": "Example Co"},
        "category": {"label": "IT Jobs"},
        "salary_min": 50000,
        "salary_max": 80000,
    }


class _FakeQuery:
    def __init__(self, rows=None):
        self._rows = rows or []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, sources=None, postings=None):
        self._sources = sources or []
        self._postings = postings or []

    def query(self, *models):
        if DataSource in models:
            return _FakeQuery(self._sources)
        if JobPosting in models:
            return _FakeQuery(self._postings)
        return _FakeQuery([])

    def add(self, *args, **kwargs):
        return None

    def flush(self):
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


class _FakeJobService:
    def __init__(self):
        self.calls = {"create_job": [], "raw_records": [], "audit": []}

    def get_or_create_source(self, db, source_key, defaults):
        s = SimpleNamespace()
        s.source_id = uuid4()
        s.source_key = source_key
        s.source_type = "api"
        s.tenant_id = None
        s.retry_policy = defaults.get("retry_policy", {})
        return s

    def create_job(self, db, source, job_type, triggered_by, parameters=None):
        job = SimpleNamespace()
        job.job_id = uuid4()
        job.source_id = source.source_id
        job.tenant_id = source.tenant_id
        job.job_type = job_type
        job.status = "queued"
        job.triggered_by = triggered_by
        job.parameters = parameters or {}
        self.calls["create_job"].append(job)
        return job

    def mark_running(self, db, job, total=0):
        job.status = "running"
        return job

    def update_progress(self, db, job, current=None, total=None, loaded_delta=0, failed_delta=0, seen_delta=0):
        return job

    def add_raw_record(self, db, job, record_type, raw_payload, source_record_id=None, storage_uri=None,
                       content_hash=None, validation_status="valid", normalised_payload=None):
        record = SimpleNamespace(
            job_id=job.job_id, record_type=record_type, source_record_id=source_record_id,
            validation_status=validation_status, normalised_payload=normalised_payload,
        )
        self.calls["raw_records"].append(record)
        return record

    def mark_completed(self, db, job, status="completed"):
        job.status = status
        return job

    def mark_failed(self, db, job, error, failure_stage="execution", failure_category="unknown",
                    retryable=None, diagnostic_payload=None):
        job.status = "failed"
        job.error_summary = error
        return job


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


def _spec(**overrides):
    base = dict(what="developer", where="South Africa", page_size=50, page_start=1,
                page_end=None, date_from=None, date_to=None, sort_by="date",
                sort_direction="down", requests_per_minute=30)
    base.update(overrides)
    return SimpleNamespace(**base)


def _run_import(captured, **overrides):
    fake_db = _FakeDB(sources=[])
    return adzuna_paginated_importer.import_pages(
        db=fake_db,
        payload=_spec(**overrides),
        actor_type="user",
        actor_id="uat-analyst-001",
    ), fake_db


# ------------------------------------------------------------------ bounds
def test_compute_spec_defaults_and_hard_caps():
    spec = adzuna_paginated_importer.compute_spec(_spec())
    assert spec["page_start"] == 1
    assert spec["page_end"] == 10
    assert spec["pages"] == DEFAULT_PAGE_RANGE == 10
    assert spec["page_size"] == PAGE_SIZE_MAX == 50
    assert spec["server_page_cap"] == PAGE_NUMBER_MAX == 250
    assert spec["max_pages_per_run"] == MAX_PAGES_PER_RUN == 250

    wide = adzuna_paginated_importer.compute_spec(_spec(page_start=240, page_end=9999))
    assert wide["page_end"] == 250
    assert wide["pages"] == 11 <= MAX_PAGES_PER_RUN

    clamped = adzuna_paginated_importer.compute_spec(_spec(page_start=1, page_end=1000))
    assert clamped["page_end"] == 250
    assert clamped["pages"] == MAX_PAGES_PER_RUN


def test_estimate_is_server_side_math_only(monkeypatch):
    monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", boom)
    result = adzuna_paginated_importer.estimate(_spec(page_start=1, page_end=10))
    assert result["pages"] == 10
    assert result["max_records_upper_bound"] == 500
    assert result["requests"] == 10
    assert result["safe_batch"] is True
    assert result["wall_time_estimate_seconds"] > 0


def boom(*a, **k):
    raise AssertionError("estimate must not call the network")


# ---------------------------------------------------------------- main run
def test_import_pages_1_and_2_with_expected_params(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()
    captured = {}
    try:
        page_bodies = {
            1: _resp({"count": 2, "results": [_adzuna_row(1, "2026-08-01T00:00:00Z"), _adzuna_row(2, "2026-08-02T00:00:00Z")]}),
            2: _resp({"count": 2, "results": [_adzuna_row(3, "2026-08-03T00:00:00Z")]}),
        }

        def fake_get(url, params=None, timeout=None):
            captured.setdefault("calls", []).append({"url": url, "params": params})
            return page_bodies[int(url.rsplit("/", 1)[1])]

        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        job_service = _FakeJobService()
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", job_service)

        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        summary, _ = _run_import({}, page_start=1, page_end=2)
        assert len(captured["calls"]) == 2
        assert captured["calls"][0]["url"].endswith("/search/1")
        assert captured["calls"][1]["url"].endswith("/search/2")
        for call in captured["calls"]:
            assert call["params"]["results_per_page"] == 50
            assert call["params"]["sort_by"] == "date"
            assert call["params"]["sort_direction"] == "down"
            assert call["params"]["what"] == "developer"
            assert call["params"]["where"] == "South Africa"
        assert summary["inserted"] == 3
        assert summary["duplicate"] == 0
        assert summary["pages_requested"] == 2
        assert summary["pages_succeeded"] == 2
        assert summary["stop_reason"] == "limit_reached"
        job = job_service.calls["create_job"][0]
        assert job.job_type == "adzuna_paginated_import"
        assert job.parameters["acquisition_mode"] == "live_trial_uat"
        assert job.parameters["empirical_use_permitted"] is True
        assert job.parameters["permission_status"] == "written_academic_permission"
        assert job.parameters["permission_received_at"] == "2026-09-10"
        assert job.parameters["attribution_required"] is True
        assert job.parameters["attribution_url"] == "https://www.adzuna.co.za"
    finally:
        monkeypatch.undo()


def test_date_filtering_is_client_side(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()

    def fake_get(url, params=None, timeout=None):
        return _resp({"count": 3, "results": [
            _adzuna_row(1, "2026-07-15T00:00:00Z"),
            _adzuna_row(2, "2026-08-20T00:00:00Z"),
            _adzuna_row(3, "2026-09-05T00:00:00Z"),
        ]})

    countable = {"audit": 0}
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", _FakeJobService())
        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event",
                           lambda db, **k: countable.__setitem__("audit", countable["audit"] + 1))

        summary, _ = _run_import({}, page_start=1, page_end=1, date_from="2026-08-01", date_to="2026-08-31")
        assert summary["records_returned"] == 3
        assert summary["records_date_filtered"] == 2
        assert summary["inserted"] == 1
        assert list(store.keys()) == ["ADZUNA-TRIAL-2"]
    finally:
        monkeypatch.undo()


def test_rerun_same_range_duplicates_never_overwritten(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()

    page_bodies = {
        1: _resp({"count": 1, "results": [_adzuna_row(1, "2026-08-01T00:00:00Z")]}),
        2: _resp({"count": 1, "results": [_adzuna_row(2, "2026-08-02T00:00:00Z")]}),
    }

    def fake_get(url, params=None, timeout=None):
        return page_bodies[int(url.rsplit("/", 1)[1])]

    store = {}
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        jobs = []
        job_service = _FakeJobService()

        def fake_insert(db, payload):
            if payload["job_id"] in store:
                return "duplicate"
            store[payload["job_id"]] = dict(payload)
            return "inserted"

        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", job_service)
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            fake_insert)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        first, _ = _run_import({}, page_start=1, page_end=2)
        assert first["inserted"] == 2

        second, _ = _run_import({}, page_start=1, page_end=2)
        assert second["inserted"] == 0
        assert second["duplicate"] == 2
        # The two original rows are untouched and not replaced.
        assert len(store) == 2
    finally:
        monkeypatch.undo()


def test_partial_page_failure_retries_then_recovers(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()
    attempts = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/search/1"):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return _resp(None, status_code=500)
            return _resp({"count": 1, "results": [_adzuna_row(1, "2026-08-01T00:00:00Z")]})
        return _resp({"count": 1, "results": [_adzuna_row(2, "2026-08-01T00:00:00Z")]})

    sleeps = []
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", sleeps.append)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", _FakeJobService())
        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        summary, _ = _run_import({}, page_start=1, page_end=2, requests_per_minute=600)
        assert summary["pages_succeeded"] == 2
        assert summary["pages_failed"] == 0
        assert summary["inserted"] == 2
        assert attempts["count"] == 2  # initial 500 then retry success
        assert sleeps and sleeps[0] == 2  # BACKOFF_SECONDS[0]
    finally:
        monkeypatch.undo()


def test_stops_on_empty_page_and_never_requests_beyond(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()
    requested = []

    def fake_get(url, params=None, timeout=None):
        page = int(url.rsplit("/", 1)[1])
        requested.append(page)
        if page == 3:
            raise AssertionError("must not request a page after an empty page")
        if page == 2:
            return _resp({"count": 0, "results": []})
        return _resp({"count": 1, "results": [_adzuna_row(1, "2026-08-01T00:00:00Z")]})

    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", _FakeJobService())
        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        summary, _ = _run_import({}, page_start=1, page_end=3)
        assert requested == [1, 2]
        assert summary["pages_empty"] == 1
        assert summary["stop_reason"] == "empty_page"
        assert summary["pages_attempted"] == 2
    finally:
        monkeypatch.undo()


def test_http_429_rate_limit_honours_retry_after(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()
    attempts = {"count": 0}

    def fake_get(url, params=None, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return _resp(None, status_code=429, headers={"Retry-After": "0.5"})
        return _resp({"count": 1, "results": [_adzuna_row(1, "2026-08-01T00:00:00Z")]})

    sleeps = []
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", sleeps.append)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", _FakeJobService())
        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        summary, _ = _run_import({}, page_start=1, page_end=1)
        assert summary["pages_succeeded"] == 1
        assert summary["inserted"] == 1
        assert attempts["count"] == 2
        assert sleeps[0] == 0.5
    finally:
        monkeypatch.undo()


def test_consecutive_failures_abort_before_range_exhausted(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()
    requested = []

    def fake_get(url, params=None, timeout=None):
        page = int(url.rsplit("/", 1)[1])
        requested.append(page)
        if page > 3:
            raise AssertionError("run must abort after 3 consecutive failures")
        return _resp(None, status_code=500)

    from app.services.ingestion.adzuna_paginated_importer import AdzunaPaginationError
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", _FakeJobService())
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: "inserted")
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event", lambda db, **k: None)

        with pytest.raises(AdzunaPaginationError) as excinfo:
            _run_import({}, page_start=1, page_end=5)
        assert excinfo.value.status_code == 502
        assert sorted(set(requested)) == [1, 2, 3]
        assert len(requested) == 9  # 3 pages x (1 attempt + 2 retries)
    finally:
        monkeypatch.undo()


def test_audit_metadata_and_job_parameters(monkeypatch):
    monkeypatch = pytest.MonkeyPatch()

    def fake_get(url, params=None, timeout=None):
        return _resp({"count": 1, "results": [_adzuna_row(9, "2026-08-01T00:00:00Z")]})

    job_service = _FakeJobService()
    try:
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.requests.get", fake_get)
        monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.ingestion_job_service", job_service)
        store = {}
        monkeypatch.setattr(
            "app.services.ingestion.adzuna_paginated_importer.job_advert_file_connector.insert_job_posting_if_absent",
            lambda db, p: ("duplicate" if p["job_id"] in store else (store.__setitem__(p["job_id"], p), "inserted")[1]))
        monkeypatch.setattr("app.services.ingestion.adzuna_paginated_importer.log_audit_event",
                           lambda db, **k: None)

        summary, _ = _run_import({}, page_start=1, page_end=1)
        job = job_service.calls["create_job"][0]
        assert job.parameters["query"]["page_start"] == 1
        assert job.parameters["query"]["page_size"] == 50
        assert job.parameters["summary"]["inserted"] == 1
        assert job.parameters["page_outcomes"][0]["page"] == 1
        assert job.parameters["page_outcomes"][0]["url"].endswith("/search/1")

        records = job_service.calls["raw_records"]
        assert [r.validation_status for r in records] == ["valid"]
        assert records[0].source_record_id == "ADZUNA-TRIAL-9"
        assert records[0].record_type == "adzuna_job_payload"
        assert records[0].normalised_payload["metadata"]["adzuna_page"] == 1
        assert records[0].normalised_payload["source"] == "ADZUNA_TRIAL_NOT_EMPIRICAL"
    finally:
        monkeypatch.undo()


# ----------------------------------------------------------- portal contract
def test_import_pages_validation_bounds(authed_client):
    client, _ = authed_client
    assert client.post("/api/v1/ingestion/adzuna/pages/estimate", json={
        "what": "x", "page_size": 51, "page_start": 1}).status_code == 422
    assert client.post("/api/v1/ingestion/adzuna/pages/estimate", json={
        "what": "x", "page_start": 251}).status_code == 422
    assert client.post("/api/v1/ingestion/adzuna/pages/estimate", json={
        "what": "x", "date_from": "not-a-date"}).status_code == 422
    assert client.post("/api/v1/ingestion/adzuna/pages/estimate", json={
        "what": "", "page_start": 1}).status_code == 422


def test_estimate_route_returns_bounded_preview(authed_client):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    try:
        response = client.post("/api/v1/ingestion/adzuna/pages/estimate", json={
            "what": "developer", "where": "South Africa", "page_size": 50,
            "page_start": 1, "page_end": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["pages"] == 10
        assert body["max_records_upper_bound"] == 500
        assert body["safe_batch"] is True
        assert body["server_page_cap"] == 250
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_import_pages_missing_credentials_is_503(authed_client, monkeypatch):
    client, _ = authed_client
    app.dependency_overrides[get_db] = lambda: _FakeDB()
    try:
        monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
        monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
        response = client.post("/api/v1/ingestion/adzuna/import-pages", json={
            "what": "developer", "where": "South Africa", "page_start": 1, "page_end": 1})
        assert response.status_code == 503
        assert "credentials" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ------------------------------------------------- create-only persistence
def test_insert_job_posting_if_absent_is_create_only(monkeypatch):
    from app.services.ingestion.adzuna_paginated_importer import job_advert_file_connector as fc_module
    existing = SimpleNamespace(job_id="ADZUNA-TRIAL-1", job_title="Old")
    fake_db = _FakeDB(postings=[existing])

    result = fc_module.insert_job_posting_if_absent(fake_db, {
        "job_id": "ADZUNA-TRIAL-1", "job_title": "New", "job_description": "x"})
    assert result == "duplicate"
    assert existing.job_title == "Old"  # untouched, never overwritten

    fake_db = _FakeDB(postings=[])
    inserted = fc_module.insert_job_posting_if_absent(fake_db, {
        "job_id": "ADZUNA-TRIAL-2", "job_title": "New", "job_description": "x"})
    assert inserted == "inserted"