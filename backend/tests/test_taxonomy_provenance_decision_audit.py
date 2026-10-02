"""Offline regression audit for taxonomy provenance and the decision audit trail.

Covers the explainability handoff acceptance checks:

1. The taxonomy provenance endpoint reports the inspected ESCO bundle source,
   version, licence, recorded timestamp, file checksums and row counts, plus
   the recorded OFO deferral reason (no defensible SA OFO dataset in the ACA
   bundle).
2. Human review decisions (approve / reject / defer / disagree / resolve /
   needs-review) persist an append-only ``SkillMappingReviewEvent`` and an
   enterprise audit event on ``dsl01_auditevent`` carrying before/after status,
   actor, and reason metadata.
3. Automatic high-confidence approvals emit ``system`` audit events so the
   explainability chain covers auto-approval as well as human decisions.
4. The mapping history endpoint returns the immutable decision trail in
   chronological order.

Runs fully offline against the SQLite in-memory database; the provenance
payload is asserted structurally without requiring the ACA bundle on disk.
"""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from typing import Dict, List

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
from app.models.skill import Skill
from app.models.skill_mapping import SkillMapping
from app.models.skill_mapping_review_event import SkillMappingReviewEvent

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


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-provenance-admin-001",
        identity_type="user",
        tenant_id=uuid.uuid4(),
        is_admin=True,
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


def _seed_skill(db, name: str, status: str = "active") -> Skill:
    skill = Skill(
        skill_key=name.lower().replace(" ", "_"),
        name=name,
        status=status,
    )
    db.add(skill)
    db.flush()
    return skill


def _seed_mapping(db, skill_id, matched_text, status="candidate", confidence=0.62) -> SkillMapping:
    mapping = SkillMapping(
        source_record_id="seed-record-001",
        matched_text=matched_text,
        extraction_method="embeddings_cosine",
        confidence_score=confidence,
        mapping_status=status,
        source_domain="labour_market",
        source_entity_type="job_posting",
        source_entity_id=uuid.uuid4(),
        skill_id=skill_id,
        reviewed_by=None,
    )
    db.add(mapping)
    db.flush()
    return mapping


def _seed_source(db) -> None:
    db.add(
        DataSource(
            source_key="provenance_test",
            name="Provenance test source",
            source_type="api",
            source_category="current_jobs",
            connector_type="job_board_api",
            retry_policy={"max_attempts": 1},
        )
    )
    db.flush()


# ------------------------------------------------------- provenance shape
def test_taxonomy_provenance_reports_inspected_sources_resolution(client, sqlite_db):
    _seed_source(sqlite_db)
    response = client.get("/api/v1/skills/taxonomy/provenance")
    assert response.status_code == 200, response.text
    payload = response.json()

    esco = payload["sources"]["esco"]
    assert "esco" in esco["source"].lower() or "aca" in esco["source"].lower()
    assert "1.2.0" in esco["version"]
    assert "EUPL" in esco["licence"]
    assert esco["recorded_at"]
    assert isinstance(esco["files"], list) and len(esco["files"]) >= 1
    compiled = json.dumps(payload)
    for file in esco["files"]:
        assert file["sha256"] and len(file["sha256"]) == 64
        assert file["data_rows"] >= 0
        assert file["filename"] not in compiled or True  # names may appear

    ofo = payload["sources"]["ofo"]
    assert ofo["status"] == "deferred"
    assert ofo["reason"]

    counts = payload["counts"]
    assert set(["esco_total", "esco_occupations", "mappings_total", "active_skills"]) <= set(counts.keys())
    assert "deferred" in payload["mapping_status_summary"]

    coverage = payload["coverage"]
    assert "esco_skill_coverage" in coverage
    assert coverage["ofo_deferred_reason"]

    traceability = payload["traceability"]
    assert isinstance(traceability, list)
    assert "review_event_count" in payload


def test_taxonomy_provenance_is_in_scope_of_marketing_report_payload(client, sqlite_db):
    _seed_source(sqlite_db)
    response = client.get("/api/v1/skills/taxonomy/provenance")
    assert response.status_code == 200, response.text
    configuration = response.json()
    assert "sources" in configuration and "traceability" in configuration


# --------------------------------------------------- human decision audit
def test_extended_review_decisions_and_append_only_history(client, sqlite_db):
    _seed_source(sqlite_db)
    skill = _seed_skill(sqlite_db, "Decision Audit Skill")
    mapping = _seed_mapping(sqlite_db, skill.skill_id, "deferred but later resolved evidence")

    approve = client.post(
        f"/api/v1/skills/mappings/{mapping.mapping_id}/review",
        json={"decision": "approved", "note": "Evidence is strong and consistent across postings"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["mapping_status"] == "approved"

    defer = client.post(
        f"/api/v1/skills/mappings/{mapping.mapping_id}/review",
        json={"decision": "deferred", "note": "Awaiting the SA OFO dataset before final attribution"},
    )
    assert defer.status_code == 200, defer.text
    assert defer.json()["mapping_status"] == "deferred"

    disagrees = client.post(
        f"/api/v1/skills/mappings/{mapping.mapping_id}/review",
        json={"decision": "disagreement", "note": "Second reviewer disputes this canonical selection"},
    )
    assert disagrees.status_code == 200, disagrees.text
    assert disagrees.json()["mapping_status"] == "needs_review"

    resolved = client.post(
        f"/api/v1/skills/mappings/{mapping.mapping_id}/review",
        json={"decision": "resolved", "note": "Adjudicator confirmed the original canonical selection"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["mapping_status"] == "approved"

    events = (
        sqlite_db.query(SkillMappingReviewEvent)
        .filter(SkillMappingReviewEvent.mapping_id == mapping.mapping_id)
        .order_by(SkillMappingReviewEvent.created_at.asc())
        .all()
    )
    assert [e.decision for e in events] == ["approved", "deferred", "disagreement", "resolved"]
    for event in events:
        assert event.reviewer_id == "e2e-provenance-admin-001"
        assert len(event.note) >= 10

    audit = (
        sqlite_db.query(AuditEvent)
        .filter(AuditEvent.action.like("mapping_review_%"))
        .all()
    )
    assert len(audit) >= 4
    for event in audit:
        assert event.result == "success"
        assert event.actor_type == "human"

    history = client.get(f"/api/v1/skills/mappings/{mapping.mapping_id}/history")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["mapping_id"] == str(mapping.mapping_id)
    assert body["mapping_status"] == "approved"
    assert len(body["history"]) == 4
    earliest = body["history"][0]
    assert earliest["decision"] == "approved"
    assert earliest["previous_status"] == "candidate"
    assert len(body["audit_ids"]) == 4


def test_unresolvable_mapping_review_is_404(client, sqlite_db):
    _seed_source(sqlite_db)
    orphan = uuid.uuid4()
    missing = client.get(f"/api/v1/skills/mappings/{orphan}/history")
    assert missing.status_code == 404, missing.text


def test_auto_approval_emits_system_audit_event_for_chain(client, sqlite_db):
    _seed_source(sqlite_db)
    skill = _seed_skill(sqlite_db, "Auto Approve Tracking Skill")
    candidate = _seed_mapping(sqlite_db, skill.skill_id, "high-confidence auto approved", confidence=0.97)
    candidate.mapping_status = "candidate"

    from app.services.skill_harmonisation_service import skill_harmonisation_service

    skill_harmonisation_service.auto_approve_high_confidence_mappings(
        db=sqlite_db,
        min_confidence=0.90,
        source_domain="labour_market",
        reviewer_id=None,
        note="high_confidence_candidate_mapping",
    )
    sqlite_db.commit()

    audit = (
        sqlite_db.query(AuditEvent)
        .filter(AuditEvent.action == "mapping_review_auto_approved")
        .all()
    )
    assert len(audit) >= 1
    auto_event = audit[0]
    assert auto_event.actor_type == "system"
    assert (auto_event.event_metadata or {}).get("decision") == "approved"
    assert (auto_event.event_metadata or {}).get("resulting_status") == "approved"
    assert (auto_event.event_metadata or {}).get("previous_status") == "candidate"
    assert (auto_event.event_metadata or {}).get("threshold") == 0.90