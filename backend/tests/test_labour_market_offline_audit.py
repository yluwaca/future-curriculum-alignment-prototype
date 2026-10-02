"""Final offline readiness audit for the labour-market workflow.

Covers the ten audit checklist items that need executable proof:

1. RBAC contract on the labour-market endpoints (401 anon, 403 viewer,
   analyst/administrator allowed) including the read-only report endpoint.
2. Analyst single-mapping decisions (approve/reject) plus the immutable
   ``SkillMappingReviewEvent`` audit trail, and 422 validation for short
   notes and unknown mapping ids.
3. Importer resilience to malformed provider responses (non-JSON 200,
   non-dict body, ``results`` not a list, non-dict items, missing id).
4. Request pacing between pages using the effective requests-per-minute.
5. Failed-job retry safety: a partially failed run can be re-run over the
   same range without inserting duplicate rows.
6. Signal-generation promotion gate: rejected mappings never reach demand
   signals or evidence.
7. Structured logging breadcrumbs that never leak credentials or full
   advert text.
8. Pagination boundaries on the saved-posts API and spec clamp rules.
9. The read-only provider readiness report reflects imports, mappings,
   reviews and signal runs, and never leaks ``auth_config``.

Everything runs offline against the SQLite in-memory database and the
stdlib loopback synthetic provider.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from types import SimpleNamespace
from typing import Dict, List, Optional

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
from app.models.base import Base
from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.pipeline_run import PipelineRun
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.skill import Skill
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.models.skill_mapping_review_event import SkillMappingReviewEvent
from app.services.ingestion.adzuna_paginated_importer import adzuna_paginated_importer

from tests.synthetic_job_provider import SYNTHETIC_DESCRIPTIONS, SyntheticJobBoard

try:
    from pgvector.sqlalchemy import Vector as PgVector

    @compiles(PgVector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "VECTOR"
except Exception:  # pragma: no cover - pgvector is an optional test dependency
    pass


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


SYNTHETIC_SOURCE_LABEL = "SYNTHETIC_JOB_BOARD"
SYNTHETIC_SOURCE_KEY = "synthetic_jobs_api"
IMPORTER_LOGGER = "app.services.ingestion.adzuna_paginated_importer"


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-analyst-001",
        identity_type="user",
        tenant_id=uuid.uuid4(),
        is_admin=True,
        roles=[],
    )


def _analyst_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-analyst-002",
        identity_type="user",
        tenant_id=uuid.uuid4(),
        is_admin=False,
        roles=[SimpleNamespace(role_id="analyst")],
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
        source_key=SYNTHETIC_SOURCE_KEY,
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

    admin_user = _admin_user()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def synthetic_env():
    with SyntheticJobBoard() as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        yield board
        os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)


def _import_payload(page_start: int = 1, page_end: int = 2, page_size: int = 3,
                    requests_per_minute: int = 120) -> Dict:
    return {
        "what": "developer",
        "where": "South Africa",
        "page_size": page_size,
        "page_start": page_start,
        "page_end": page_end,
        "requests_per_minute": requests_per_minute,
    }


def _import_synthetic(client, **overrides):
    return client.post(
        "/api/v1/ingestion/adzuna/import-pages?provider=synthetic",
        json=_import_payload(**overrides),
    )


def _run_pipeline(client) -> None:
    response = client.post(
        "/api/v1/labour-market/jobs/skill-pipeline",
        json={"limit": 100, "sources": [SYNTHETIC_SOURCE_LABEL]},
    )
    assert response.status_code == 200, response.text


def _run_signals(client) -> Dict:
    response = client.post(
        "/api/v1/labour-market/jobs/skill-pipeline/signals",
        json={"limit": 100, "sources": [SYNTHETIC_SOURCE_LABEL]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _candidate_mappings(sqlite_db) -> List[SkillMapping]:
    return (
        sqlite_db.query(SkillMapping)
        .filter(
            SkillMapping.source_domain == "labour_market",
            SkillMapping.source_entity_type == "job_posting",
            SkillMapping.mapping_status == "candidate",
        )
        .all()
    )


# --------------------------------------------------------------- RBAC gate
def test_report_and_labour_endpoints_rbac_contract(client):
    app.dependency_overrides.pop(get_current_user, None)
    report_url = "/api/v1/labour-market/jobs/provider-readiness-report"
    assert client.get(report_url).status_code == 401
    assert client.get("/api/v1/labour-market/jobs/skill-pipeline/signals").status_code == 401
    assert client.get("/api/v1/ingestion/adzuna/posts?provider=synthetic").status_code == 401

    app.dependency_overrides[get_current_user] = lambda: _viewer_user()
    assert client.get(report_url).status_code == 403, "viewer must not read the report"
    assert client.post(
        "/api/v1/labour-market/jobs/skill-pipeline", json={"limit": 100}
    ).status_code == 403
    # The trial-signals list endpoint is intentionally readable by any
    # authenticated user (read-only view), matching list_skill_pipeline_runs.
    assert client.get("/api/v1/labour-market/jobs/skill-pipeline/signals").status_code == 200

    app.dependency_overrides[get_current_user] = lambda: _analyst_user()
    report = client.get(report_url)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["scope"]["sources"] == [SYNTHETIC_SOURCE_KEY]
    assert body["rows"][0]["source"]["source_key"] == SYNTHETIC_SOURCE_KEY
    assert body["rows"][0]["postings"]["total"] == 0  # nothing imported yet


# -------------------------------------------------- single mapping review
def test_single_mapping_review_approve_and_reject_audit_events(
    client, synthetic_env, sqlite_db, monkeypatch
):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    import_resp = _import_synthetic(client)
    assert import_resp.status_code == 200, import_resp.text
    _run_pipeline(client)
    candidates = _candidate_mappings(sqlite_db)
    assert len(candidates) >= 2

    approve = candidates[0]
    reject = next(c for c in candidates if c.skill_id != candidates[0].skill_id)

    approve_resp = client.post(
        f"/api/v1/skills/mappings/{approve.mapping_id}/review",
        json={"decision": "approved", "note": "Demand evidence supports approval"},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["mapping_status"] == "approved"

    reject_resp = client.post(
        f"/api/v1/skills/mappings/{reject.mapping_id}/review",
        json={"decision": "rejected", "note": "Skill appears spuriously in this posting"},
    )
    assert reject_resp.status_code == 200, reject_resp.text
    assert reject_resp.json()["mapping_status"] == "rejected"

    events = sqlite_db.query(SkillMappingReviewEvent).order_by(
        SkillMappingReviewEvent.created_at.asc()
    ).all()
    assert len(events) == 2
    decisions = {event.decision for event in events}
    assert decisions == {"approved", "rejected"}
    for event in events:
        assert event.reviewer_id == "e2e-analyst-001"
        assert event.previous_status == "candidate"
        assert len(event.note) >= 10

    approved_event = next(e for e in events if e.decision == "approved")
    assert approved_event.mapping_id == approve.mapping_id
    rejected_event = next(e for e in events if e.decision == "rejected")
    assert rejected_event.mapping_id == reject.mapping_id


def test_single_mapping_review_validation_errors(client, synthetic_env, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    _import_synthetic(client)
    _run_pipeline(client)
    candidates = _candidate_mappings(sqlite_db)
    assert candidates

    target = candidates[0]
    short = client.post(
        f"/api/v1/skills/mappings/{target.mapping_id}/review",
        json={"decision": "approved", "note": "short"},
    )
    assert short.status_code == 422, short.text

    missing = client.post(
        f"/api/v1/skills/mappings/{uuid.uuid4()}/review",
        json={"decision": "approved", "note": "This note is long enough to pass"},
    )
    assert missing.status_code == 422, missing.text

    assert sqlite_db.query(SkillMappingReviewEvent).count() == 0


def test_rejected_mapping_is_never_promoted_to_signals(
    client, synthetic_env, sqlite_db, monkeypatch
):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    _import_synthetic(client)
    _run_pipeline(client)
    candidates = _candidate_mappings(sqlite_db)
    assert len(candidates) >= 2

    approve = candidates[0]
    reject = next(c for c in candidates if c.skill_id != candidates[0].skill_id)

    assert client.post(
        f"/api/v1/skills/mappings/{approve.mapping_id}/review",
        json={"decision": "approved", "note": "Approved on analyst review"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/skills/mappings/{reject.mapping_id}/review",
        json={"decision": "rejected", "note": "Rejected on analyst review"},
    ).status_code == 200

    result = _run_signals(client)
    assert result["mappings_approved_used"] >= 1
    assert result["signals_created"] >= 1
    assert result["promotion_gate"] == "approved_labour_mappings_only"

    evidence_skills = {row[0] for row in sqlite_db.query(SkillDemandEvidence.skill_id).all()}
    assert approve.skill_id in evidence_skills
    assert reject.skill_id not in evidence_skills

    rejected_name = (
        sqlite_db.query(Skill.name).filter(Skill.skill_id == reject.skill_id).scalar()
    )
    promoted_dimensions = {
        row[0]
        for row in sqlite_db.query(LabourMarketSignal.dimension_value).all()
    }
    assert rejected_name not in promoted_dimensions


# --------------------------------------------------- malformed responses
def test_import_non_json_200_body_retries_then_fails_502(client, monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: sleeps.append(s))
    with SyntheticJobBoard(malformed_responses={1: ("definitely not json", "text/plain")}) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            response = _import_synthetic(client, page_start=1, page_end=1, page_size=3)
            hits = list(board.httpd.hits)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert response.status_code == 502, response.text
    assert "unexpected response format" in response.json()["detail"]
    assert hits == [1, 1, 1], "non-JSON 200 bodies must be retried MAX_RETRIES_PER_PAGE times"
    assert len(sleeps) == 3  # one backoff sleep after each unsuccessful JSON parse attempt


def test_import_results_not_a_list_is_page_error(client, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    with SyntheticJobBoard(malformed_responses={1: ('{"results": 42, "count": 1}', "application/json")}) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            response = _import_synthetic(client, page_start=1, page_end=1, page_size=3)
            hits = list(board.httpd.hits)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert response.status_code == 502, response.text
    assert "unexpected response format" in response.json()["detail"]
    assert hits == [1]  # valid JSON parses once; the schema check fails without retries


def test_import_counts_non_dict_results_items_as_failed(client, synthetic_env, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    with SyntheticJobBoard(total_pages=2, malformed_responses={
        2: (
            json.dumps({"results": [_one_synthetic_row("audit-partial-2"), "garbage"], "count": 2}),
            "application/json",
        ),
    }) as board:
        board.pages[1] = [_one_synthetic_row("audit-partial-1")]
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            response = _import_synthetic(client, page_start=1, page_end=2, page_size=3)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pages_succeeded"] == 2
    assert body["inserted"] == 2
    assert body["failed"] == 1
    assert body["stop_reason"] == "limit_reached"

    job = sqlite_db.query(IngestionJob).filter(IngestionJob.job_type == "synthetic_paginated_import").first()
    assert job.status == "completed_with_errors"


def test_import_tolerates_items_without_natural_ids(client, synthetic_env, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    broken = _one_synthetic_row("audit-no-id")
    broken.pop("id")
    with SyntheticJobBoard(total_pages=1, malformed_responses={
        1: (json.dumps({"results": [broken], "count": 1}), "application/json"),
    }) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            response = _import_synthetic(client, page_start=1, page_end=1, page_size=5)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pages_succeeded"] == 1
    assert body["inserted"] == 1
    assert body["failed"] == 0
    job = sqlite_db.query(JobPosting).first()
    assert job is not None
    assert sqlite_db.query(RawIngestionRecord).filter(
        RawIngestionRecord.validation_status == "failed"
    ).count() == 0  # tolerated, not archived as failed


def _one_synthetic_row(ad_id: str) -> Dict:
    from tests.synthetic_job_provider import synthetic_row
    return synthetic_row(ad_id, "2026-08-03T09:00:00Z", "Data Engineer",
                         "Build data pipelines with Python, SQL and cloud: AWS services.")


# -------------------------------------------------------------- pacing
def test_import_paces_requests_between_pages(client, synthetic_env, monkeypatch):
    sleeps: List[float] = []
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: sleeps.append(s))
    response = _import_synthetic(client, page_start=1, page_end=2, page_size=3,
                                 requests_per_minute=60)
    assert response.status_code == 200, response.text
    assert sleeps == [1.0], "rpm=60 must insert a 1.0s pacing delay between pages"


# --------------------------------------------- failed-job retry safety
def test_rerun_same_range_after_partial_failure_has_no_duplicates(client, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)

    with SyntheticJobBoard(total_pages=2, always_error_pages={2}) as board:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = board.base_url
        try:
            first = _import_synthetic(client, page_start=1, page_end=2, page_size=3)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["pages_succeeded"] == 1
    assert first_body["pages_failed"] == 1
    assert first_body["inserted"] == 3
    assert first_body["stop_reason"] == "limit_reached"

    failed_job = sqlite_db.query(IngestionJob).filter(
        IngestionJob.job_type == "synthetic_paginated_import"
    ).order_by(IngestionJob.created_at.desc()).first()
    assert failed_job.status == "completed_with_errors"

    with SyntheticJobBoard(total_pages=2) as recovered:
        os.environ["FUTURE_SYNTHETIC_JOBS_BASE_URL"] = recovered.base_url
        try:
            second = _import_synthetic(client, page_start=1, page_end=2, page_size=3)
        finally:
            os.environ.pop("FUTURE_SYNTHETIC_JOBS_BASE_URL", None)
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["inserted"] == 3
    assert second_body["duplicate"] == 3
    assert sqlite_db.query(JobPosting).count() == 6

    page_one_rows = (
        sqlite_db.query(JobPosting)
        .filter(JobPosting.job_id.in_(["SYNTHETIC-syn-1-1", "SYNTHETIC-syn-1-2", "SYNTHETIC-syn-1-3"]))
        .all()
    )
    assert len(page_one_rows) == 3
    assert all(row.ingestion_job_id == failed_job.job_id for row in page_one_rows)


# ----------------------------------------------------- pagination bounds
def test_saved_posts_pagination_boundaries(client, synthetic_env, sqlite_db, monkeypatch):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    _import_synthetic(client, page_start=1, page_end=1, page_size=3)

    first_page = client.get(
        "/api/v1/ingestion/adzuna/posts?provider=synthetic&limit=2&offset=0"
    )
    assert first_page.status_code == 200, first_page.text
    body = first_page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    second_page = client.get(
        "/api/v1/ingestion/adzuna/posts?provider=synthetic&limit=2&offset=2"
    )
    body = second_page.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is False

    beyond = client.get(
        "/api/v1/ingestion/adzuna/posts?provider=synthetic&limit=100&offset=10"
    )
    body = beyond.json()
    assert body["total"] == 3
    assert body["items"] == []
    assert body["has_more"] is False

    spec = adzuna_paginated_importer.compute_spec(SimpleNamespace(
        what=None,
        where=None,
        page_start=0,
        page_end=0,
        page_size=999,
        date_from=None,
        date_to=None,
        sort_by="date",
        sort_direction="desc",
        requests_per_minute=0,
    ))
    assert spec["page_start"] == 1
    assert spec["page_size"] == 50
    assert spec["rate_limit"]["requests_per_minute"] == 30
    assert spec["pages"] == 1

    inverted = adzuna_paginated_importer.compute_spec(SimpleNamespace(
        what=None,
        where=None,
        page_start=9,
        page_end=2,
        page_size=5,
        date_from=None,
        date_to=None,
        sort_by="date",
        sort_direction="desc",
        requests_per_minute=120,
    ))
    assert inverted["pages"] == 1
    assert inverted["page_end"] == 9


# --------------------------------------------------- structured logging
def test_import_structured_log_never_leaks_credentials_or_advert_text(
    client, synthetic_env, caplog, monkeypatch
):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    caplog.set_level(logging.INFO, logger=IMPORTER_LOGGER)
    import_resp = _import_synthetic(client)
    assert import_resp.status_code == 200, import_resp.text

    lines = [
        record.getMessage()
        for record in caplog.records
        if record.name == IMPORTER_LOGGER
    ]
    assert lines, "the importer must emit structured log lines"
    import_events = [line for line in lines if '"event": "import_job"' in line]
    assert import_events, "an import_job structured event must be emitted"

    blob = "\n".join(lines)
    for description in SYNTHETIC_DESCRIPTIONS:
        assert description not in blob, "full advert text must never be logged"
    assert "app_id" not in blob and "app_key" not in blob


# ------------------------------------------------------- report endpoint
def test_report_endpoint_reflects_imports_mappings_and_runs(
    client, synthetic_env, sqlite_db, monkeypatch
):
    monkeypatch.setattr(adzuna_paginated_importer, "sleep", lambda s: None)
    import_resp = _import_synthetic(client)
    assert import_resp.status_code == 200, import_resp.text
    _run_pipeline(client)

    candidates = _candidate_mappings(sqlite_db)
    assert candidates
    approve_resp = client.post(
        f"/api/v1/skills/mappings/{candidates[0].mapping_id}/review",
        json={"decision": "approved", "note": "Approved as part of the readiness audit"},
    )
    assert approve_resp.status_code == 200, approve_resp.text
    _run_signals(client)

    report_resp = client.get(
        "/api/v1/labour-market/jobs/provider-readiness-report?sources=synthetic_jobs_api"
    )
    assert report_resp.status_code == 200, report_resp.text
    assert "auth_config" not in report_resp.text, "report must never expose source credentials"
    report = report_resp.json()

    assert report["report_name"] == "labour_market_provider_readiness"
    assert report["scope"]["sources"] == [SYNTHETIC_SOURCE_KEY]
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["source"]["source_key"] == SYNTHETIC_SOURCE_KEY
    assert row["postings"]["total"] == 6
    assert row["mappings"]["approved"] >= 1
    assert row["mappings"]["reviewed_count"] >= 1
    assert row["ingestion"]["job_count"] >= 1
    assert row["ingestion"]["latest_job"]["status"] in {"completed", "completed_with_errors"}
    assert row["ingestion"]["latest_job"]["job_type"] == "synthetic_paginated_import"
    assert report["global"]["signals_total"] >= 1
    assert report["global"]["latest_signal_run"]["status"] == "completed"
    assert report["global"]["latest_signal_run"]["summary"]["signals_created"] >= 1
    assert report["global"]["latest_pipeline_run"]["status"] == "completed"
    assert report["global"]["latest_pipeline_run"]["summary"]["mappings"]["mappings_created"] >= 1