"""End-to-end synthetic job-board provider test.

Runs the full labour-market path against a purely synthetic provider on a
SQLite in-memory database and a stdlib loopback HTTP server:

    import-pages (provider=synthetic) -> saved posts -> skill pipeline ->
    bulk mapping approval -> job-skill signals -> demand evidence

Also verifies the role/access gate (401 unauthenticated, 403 viewer) and the
provider boundary (unknown provider 422, missing base URL 503).

The synthetic provider mirrors the real Adzuna shape (page number in the URL
path, ``results``/``count`` payloads) but requires no credentials, which keeps
the test deterministic and free of an external network dependency.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from typing import Dict, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.base import Base
from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.services.ingestion.adzuna_paginated_importer import adzuna_paginated_importer

from tests.synthetic_job_provider import SyntheticJobBoard, synthetic_row


# SQLite has no native JSONB or UUID column types; models declare the
# Postgres dialect types, so register portable DDL renderings for tests.
@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


try:
    from pgvector.sqlalchemy import Vector as PgVector

    @compiles(PgVector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "VECTOR"
except Exception:  # pragma: no cover - pgvector is an optional test dependency
    pass


SYNTHETIC_SOURCE_LABEL = "SYNTHETIC_JOB_BOARD"


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-analyst-001",
        identity_type="user",
        tenant_id=uuid.uuid4(),
        is_admin=True,
        roles=[],
    )


def _viewer_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-viewer-001",
        identity_type="user",
        tenant_id=uuid.uuid4(),
        is_admin=False,
        roles=[],
    )


@pytest.fixture()
def sqlite_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    seed = DataSource(
        source_key="synthetic_jobs_api",
        name="Synthetic Job Board (automated test fixture)",
        source_type="api",
        source_category="current_jobs",
        connector_type="job_board_api",
        retry_policy={"max_attempts": 3, "initial_backoff_seconds": 1},
    )
    session.add(seed)
    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def client(sqlite_db):
    def override_get_db():
        yield sqlite_db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _admin_user()
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def synthetic_env():
    with SyntheticJobBoard() as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        yield board
        os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)


def _import_payload(page_start: int = 1, page_end: int = 2, page_size: int = 3) -> Dict:
    return {
        "what": "developer",
        "where": "South Africa",
        "page_size": page_size,
        "page_start": page_start,
        "page_end": page_end,
        "requests_per_minute": 120,
    }


def _import_synthetic(client, **overrides):
    return client.post(
        "/api/v1/ingestion/adzuna/import-pages?provider=synthetic",
        json=_import_payload(**overrides),
    )


# ----------------------------------------------------------------- main flow
def test_synthetic_provider_end_to_end(client, synthetic_env, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)

    import_resp = _import_synthetic(client)
    assert import_resp.status_code == 200, import_resp.text
    imported = import_resp.json()
    assert imported["provider"] == "synthetic"
    assert imported["pages_requested"] == 2
    assert imported["pages_succeeded"] == 2
    assert imported["pages_failed"] == 0
    assert imported["inserted"] == 6
    assert imported["duplicate"] == 0
    assert imported["stop_reason"] == "limit_reached"

    job = sqlite_db.query(IngestionJob).filter(IngestionJob.job_type == "synthetic_paginated_import").first()
    assert job is not None
    assert job.parameters["provider"] == "synthetic"
    assert job.parameters["acquisition_mode"] == "simulated_uat"
    assert job.parameters["empirical_use_permitted"] is None
    assert job.parameters["page_outcomes"][0]["page"] == 1

    actions = {row[0] for row in sqlite_db.query(AuditEvent.action).all()}
    assert "import_synthetic_pages" in actions and "import_synthetic_page" in actions

    posts_resp = client.get("/api/v1/ingestion/adzuna/posts?provider=synthetic&limit=100")
    assert posts_resp.status_code == 200, posts_resp.text
    posts = posts_resp.json()
    assert posts["total"] == 6
    assert posts["has_more"] is False
    job_ids = {item["job_id"] for item in posts["items"]}
    assert len(job_ids) == 6
    assert all(job_id.startswith("SYNTHETIC-") for job_id in job_ids)

    # Pipeline: candidate mappings are created from the postings (confidence
    # is below the 0.90 auto-approve gate, so mappings stay "candidate").
    pipeline_resp = client.post(
        "/api/v1/labour-market/jobs/skill-pipeline",
        json={"limit": 100, "sources": [SYNTHETIC_SOURCE_LABEL]},
    )
    assert pipeline_resp.status_code == 200, pipeline_resp.text
    pipeline = pipeline_resp.json()
    assert pipeline["mappings"]["postings_seen"] == 6
    assert pipeline["mappings"]["mappings_created"] >= 1
    assert pipeline["trial_scope"] == {}

    candidates = (
        sqlite_db.query(SkillMapping)
        .filter(SkillMapping.source_domain == "labour_market", SkillMapping.mapping_status == "candidate")
        .count()
    )
    assert candidates >= 1

    # Human-review gate: approve the candidate mappings explicitly.
    review_resp = client.post(
        "/api/v1/skills/mappings/bulk-review?decision=approved&source_domain=labour_market"
        "&min_confidence=0&limit=500&dry_run=false&max_evidence_chars=1000"
    )
    assert review_resp.status_code == 200, review_resp.text
    review = review_resp.json()
    assert review["updated"] >= 1

    approved = (
        sqlite_db.query(SkillMapping)
        .filter(SkillMapping.source_domain == "labour_market", SkillMapping.mapping_status == "approved")
        .count()
    )
    assert approved >= 1

    # Signal + evidence generation from approved mappings only.
    signals_resp = client.post(
        "/api/v1/labour-market/jobs/skill-pipeline/signals",
        json={"limit": 100, "sources": [SYNTHETIC_SOURCE_LABEL]},
    )
    assert signals_resp.status_code == 200, signals_resp.text
    signals_result = signals_resp.json()
    assert signals_result["mappings_approved_used"] == approved
    assert signals_result["signals_created"] >= 1
    assert signals_result["evidence_created"] >= 1

    db_signals = sqlite_db.query(LabourMarketSignal).all()
    assert len(db_signals) >= 1
    for signal in db_signals:
        assert signal.method == "job_skill_demand_v1"
        assert signal.unit == "normalised_posting_count"
        assert signal.signal_metadata["evidence_scope"] == "job_vacancy_evidence"
        assert signal.signal_metadata["empirical_use_permitted"] is True
        assert signal.signal_metadata["research_use"] == "empirical_subject_to_source_governance"

    evidence = sqlite_db.query(SkillDemandEvidence).all()
    assert len(evidence) >= 1
    assert evidence[0].evidence_type == "job_posting_skill_demand"

    # Portal list endpoint (user-friendly, DB-portable path).
    list_resp = client.get("/api/v1/labour-market/signals?limit=100")
    assert list_resp.status_code == 200, list_resp.text
    listed = list_resp.json()
    assert len(listed) >= 1
    assert all(item["signal_metadata"]["evidence_scope"] == "job_vacancy_evidence" for item in listed)

    # Additive / idempotent rerun: same range inserts nothing new.
    rerun = _import_synthetic(client)
    assert rerun.status_code == 200, rerun.text
    rerun_body = rerun.json()
    assert rerun_body["inserted"] == 0
    assert rerun_body["duplicate"] == 6
    assert sqlite_db.query(JobPosting).count() == 6

    records = sqlite_db.query(RawIngestionRecord).all()
    assert {r.record_type for r in records} == {"synthetic_job_payload"}
    assert {r.validation_status for r in records} == {"valid", "duplicate"}


def test_synthetic_50_row_page_is_supported(client, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    with SyntheticJobBoard(rows_per_page=50, total_pages=1) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            import_resp = _import_synthetic(client, page_start=1, page_end=1, page_size=50)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["inserted"] == 50
    assert body["records_returned"] == 50
    assert body["page_outcomes"][0]["page"] == 1


def test_import_stops_on_empty_page(client, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    with SyntheticJobBoard(total_pages=3, empty_pages={2}) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            import_resp = _import_synthetic(client, page_start=1, page_end=3, page_size=2)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["pages_attempted"] == 2
    assert body["pages_empty"] == 1
    assert body["stop_reason"] == "empty_page"
    # The synthetic server controls its own page size (3 rows/page); the
    # client-side page_size parameter is advisory, exactly like Adzuna.
    assert body["inserted"] == 3


def test_synthetic_retries_and_recovers_from_500(client, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    with SyntheticJobBoard(error_once_pages={1}) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            import_resp = _import_synthetic(client, page_start=1, page_end=1, page_size=3)
            hits = list(board.httpd.hits)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["pages_failed"] == 0
    assert body["pages_succeeded"] == 1
    assert body["inserted"] == 3
    assert hits == [1, 1]  # 500 then retry success


# ------------------------------------------------------------- access gates
def test_unauthenticated_requests_are_401(client):
    app.dependency_overrides.pop(get_current_user, None)
    assert client.get("/api/v1/ingestion/adzuna/posts?provider=synthetic").status_code == 401
    assert client.get("/api/v1/labour-market/jobs/skill-pipeline/signals").status_code == 401
    assert client.post("/api/v1/ingestion/adzuna/import-pages?provider=synthetic", json=_import_payload()).status_code == 401


def test_viewer_user_is_forbidden_from_import_and_pipeline(client):
    app.dependency_overrides[get_current_user] = lambda: _viewer_user()
    response = client.post("/api/v1/ingestion/adzuna/import-pages?provider=synthetic", json=_import_payload())
    assert response.status_code == 403, response.text

    response = client.post(
        "/api/v1/labour-market/jobs/skill-pipeline",
        json={"limit": 100, "sources": [SYNTHETIC_SOURCE_LABEL]},
    )
    assert response.status_code == 403, response.text

    # Saving postings is also role-gated.
    response = client.get("/api/v1/ingestion/adzuna/posts?provider=synthetic")
    assert response.status_code == 403, response.text


# -------------------------------------------------------- provider boundary
def test_unsupported_provider_returns_422(client):
    response = client.post("/api/v1/ingestion/adzuna/import-pages?provider=nope", json=_import_payload())
    assert response.status_code == 422, response.text
    assert "Unsupported paginated job provider" in response.json()["detail"]

    response = client.get("/api/v1/ingestion/adzuna/posts?provider=nope")
    assert response.status_code == 422, response.text


def test_missing_synthetic_base_url_returns_503(client):
    os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    response = _import_synthetic(client)
    assert response.status_code == 503, response.text
    assert "base URL" in response.json()["detail"]


def test_synthetic_row_contract_is_adzuna_compatible():
    row = synthetic_row("syn-check-1", "2026-08-03T09:00:00Z", "Data Engineer", "Python SQL AWS")
    assert {"id", "title", "description", "created", "location", "company", "category", "salary_min"} <= set(row)
    assert isinstance(row["location"], dict) and isinstance(row["company"], dict)
    assert "display_name" in row["location"] and "display_name" in row["company"]
