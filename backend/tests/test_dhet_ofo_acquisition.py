"""Offline tests for controlled DHET OFO 2021 acquisition and evidence mapping.

Acceptance coverage for the DHET OFO download handoff:

1. DHET is registered as the authoritative OFO source exactly once (idempotent),
   and the acquisition panel reports provenance URL/version/content type/size
   and SHA-256 for every acquisition.
2. A download absolutely requires explicit operator confirmation and a resolved
   allowlisted URL; unconfirmed requests are refused before any file is written.
3. The manual upload fallback records the same provenance fields; validation
   enforces a real DHET OFO workbook shape (six-digit occupation codes and
   required columns); import is versioned, checksum-verified, and idempotent per
   SHA-256. Malformed files are rejected with a visible reason.
4. OFO evidence mappings are never assigned from title-only text; approvals
   require a six-digit OFO code that already exists in the imported tables.
5. Human review decisions persist append-only review events and enterprise audit
   events.

Runs fully offline against SQLite; the stored workbook is written to a temp
directory so no repository files are touched.
"""

from __future__ import annotations

import io
import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.base import Base
from app.models.data_source import DataSource
from app.models.dhet_ofo import (
    DHETOFOAcquisition,
    OFOEvidenceMapping,
    OFOEvidenceMappingReviewEvent,
)
from app.models.ofo_taxonomy import OFOOccupation

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


def _admin_user() -> SimpleNamespace:
    return SimpleNamespace(
        identity_id="e2e-dhet-oof-admin",
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


@pytest.fixture()
def evidence_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DHET_OFO_EVIDENCE_PATH", str(tmp_path))
    return tmp_path


# ------------------------------------------------------------------ fixtures
def _build_dhet_workbook() -> bytes:
    """A minimal but structurally valid OFO 2021 workbook."""
    wb = Workbook()
    ws = wb.active
    ws.title = "OFO"
    ws.append(["OFO Code", "OFO Title", "Major group", "Skill Level", "Version", "Description"])
    ws.append(["12", "Managers and Administrators", "Major Group", "No level", "2021",
               "Management occupations"])
    ws.append(["121301", "General Manager", "Unit Group 1213", "Level 4", "2021",
               "Plans directs oversees operations budget teams production planning performance"])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _upload(client, content: bytes, filename: str = "dhet_ofo_2021.xlsx",
            content_type: str = XLSX_MIME):
    return client.post(
        "/api/v1/dhet-ofo/upload",
        files={"file": (filename, content, content_type)},
    )


def _import_workflow(client) -> dict:
    """Upload, validate, and import the valid workbook; returns latest payload."""
    upload = _upload(client, _build_dhet_workbook())
    assert upload.status_code == 200, upload.text
    acquisition_id = upload.json()["acquisition"]["acquisition_id"]

    validated = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True
    assert validated.json()["detected_version"] == "2021"

    imported = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/import")
    assert imported.status_code == 200, imported.text
    return imported.json()


# ------------------------------------------------------------ source + guards
def test_registered_source_is_idempotent_and_download_requires_confirmation(client, sqlite_db, evidence_dir):
    first = client.get("/api/v1/dhet-ofo/source")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["source"]["authority"] == "DHET"
    assert "2021" in str(payload["source"]["version"])
    assert payload["source"]["source_page_url"].startswith("https://www.dhet.gov.za")
    assert payload["acquisitions"] == []
    assert payload["latest_acquisition"] is None

    second = client.get("/api/v1/dhet-ofo/source")
    assert second.status_code == 200
    registered = (
        sqlite_db.query(DataSource)
        .filter(DataSource.source_key == "dhet_ofo_2021")
        .all()
    )
    assert len(registered) == 1

    unconfirmed = client.post("/api/v1/dhet-ofo/download", json={"confirmed": False})
    assert unconfirmed.status_code == 400
    assert "confirmation" in unconfirmed.json()["detail"].lower()

    no_url = client.post("/api/v1/dhet-ofo/download", json={"confirmed": True})
    assert no_url.status_code == 400
    assert "resolved" in no_url.json()["detail"].lower()

    provenance = client.get("/api/v1/skills/taxonomy/provenance")
    assert provenance.status_code == 200
    assert provenance.json()["sources"]["dhet_ofo"]["acquisition_count"] == 0
    assert provenance.json()["sources"]["ofo"]["status"] == "deferred"


def test_upload_validate_import_and_sha256_idempotency(client, sqlite_db, evidence_dir):
    workbook = _build_dhet_workbook()
    upload = _upload(client, workbook)
    assert upload.status_code == 200, upload.text
    result = upload.json()
    assert result["status"] == "pending_validation"
    acquisition = result["acquisition"]
    assert acquisition["method"] == "upload"
    assert len(acquisition["sha256"]) == 64
    assert acquisition["byte_size"] > 0
    assert acquisition["content_type"] == XLSX_MIME
    assert acquisition["operator_confirmed"] is True
    assert acquisition["resolved_url"].startswith("https://www.dhet.gov.za")

    acquisition_id = acquisition["acquisition_id"]
    row = (
        sqlite_db.query(DHETOFOAcquisition)
        .filter(DHETOFOAcquisition.acquisition_id == uuid.UUID(acquisition_id))
        .one()
    )
    assert row.operator_id == "e2e-dhet-oof-admin"
    assert row.retrieved_at is not None

    validated = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/validate")
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True

    imported = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/import")
    assert imported.status_code == 200, imported.text
    imported = imported.json()
    assert imported["status"] == "imported"
    assert imported["version"] == "2021"
    assert imported["counts"]["created"] == 2
    assert imported["counts"]["occupations"] == 1
    assert imported["counts"]["groups"] == 1

    occupation = (
        sqlite_db.query(OFOOccupation)
        .filter(OFOOccupation.ofo_code == "121301", OFOOccupation.taxonomy_version == "2021")
        .one()
    )
    assert occupation.broader_occupation_code == "12"
    assert occupation.occupation_metadata["source"]["authority"] == "DHET"
    assert occupation.occupation_metadata["source"]["sha256"] == acquisition["sha256"]

    group = (
        sqlite_db.query(OFOOccupation)
        .filter(OFOOccupation.ofo_code == "12", OFOOccupation.taxonomy_version == "2021")
        .one()
    )
    assert group.status == "group"

    duplicate = _upload(client, workbook)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["status"] == "idempotent"
    assert sqlite_db.query(DHETOFOAcquisition).count() == 1

    provenance = client.get("/api/v1/skills/taxonomy/provenance")
    assert provenance.status_code == 200
    body = provenance.json()
    assert body["sources"]["ofo"]["status"] == "imported"
    assert body["sources"]["ofo"]["sha256"] == acquisition["sha256"]
    assert body["counts"]["ofo_occupation_by_version"]["2021"] == 2
    assert body["coverage"]["ofo_version"] == "2021"
    assert body["sources"]["dhet_ofo"]["acquisition_count"] == 1

    audit = (
        sqlite_db.query(AuditEvent)
        .filter(AuditEvent.action.in_(["dhet_ofo_upload", "dhet_ofo_validate", "dhet_ofo_import"]))
        .all()
    )
    assert {event.action for event in audit} == {
        "dhet_ofo_upload",
        "dhet_ofo_validate",
        "dhet_ofo_import",
    }


def test_validate_rejects_non_oof_workbook(client, sqlite_db, evidence_dir):
    malformed = b"hello,world\n1,2\n"
    upload = _upload(client, malformed, filename="reject.csv", content_type="text/csv")
    assert upload.status_code == 200, upload.text
    acquisition_id = upload.json()["acquisition"]["acquisition_id"]

    validated = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/validate")
    assert validated.status_code == 200, validated.text
    body = validated.json()
    assert body["valid"] is False
    assert body["status"] == "rejected"
    assert any("Required columns are missing" in error for error in body["errors"])

    refreshed = client.get("/api/v1/dhet-ofo/source")
    malformed_row = refreshed.json()["acquisitions"][0]
    assert malformed_row["status"] == "rejected"
    assert malformed_row["validation_errors"]

    refused = client.post(f"/api/v1/dhet-ofo/acquisitions/{acquisition_id}/import")
    assert refused.status_code == 400
    assert "validated" in refused.json()["detail"]


def test_no_fabricated_codes_approval_requires_existing_dhet_code(client, sqlite_db, evidence_dir):
    _import_workflow(client)

    proposal = client.post(
        "/api/v1/dhet-ofo/mappings",
        json={
            "source_domain": "labour_market",
            "source_entity_type": "job_posting",
            "matched_text": "General Manager",
            "duties_text": "Plans and directs operations, manages budgets, leads production "
                           "teams and drives performance planning",
            "skills_text": "operations management, budgeting, production planning",
            "version": "2021",
        },
    )
    assert proposal.status_code == 201, proposal.text
    mapping = proposal.json()
    assert mapping["mapping_status"] == "candidate"
    assert mapping["ofo_code"] == "121301"
    assert mapping["method"] == "evidence_semantic"
    assert mapping["confidence_score"] >= 0.30

    fabricated = client.post(
        f"/api/v1/dhet-ofo/mappings/{mapping['mapping_id']}/review",
        json={
            "decision": "approved",
            "note": "Reviewer confirms this evidence maps to the selected occupation",
            "selected_ofo_code": "999999",
        },
    )
    assert fabricated.status_code == 400
    assert "does not exist" in fabricated.json()["detail"]

    approved = client.post(
        f"/api/v1/dhet-ofo/mappings/{mapping['mapping_id']}/review",
        json={
            "decision": "approved",
            "note": "Reviewer confirms this evidence maps to the selected occupation",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["mapping_status"] == "approved"
    assert approved.json()["ofo_code"] == "121301"

    history = client.get(f"/api/v1/dhet-ofo/mappings/{mapping['mapping_id']}/history")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["mapping_status"] == "approved"
    assert len(body["history"]) == 1
    assert body["history"][0]["decision"] == "approved"
    assert body["history"][0]["previous_status"] == "candidate"
    assert body["history"][0]["ofo_code_after"] == "121301"

    audit = (
        sqlite_db.query(AuditEvent)
        .filter(AuditEvent.action.like("ofo_mapping_review_%"))
        .all()
    )
    assert len(audit) == 1
    assert audit[0].result == "success"
    assert audit[0].actor_type == "human"
    assert (audit[0].event_metadata or {}).get("decision") == "approved"


def test_title_only_probe_is_never_approved(client, sqlite_db, evidence_dir):
    _import_workflow(client)

    title_only = client.post(
        "/api/v1/dhet-ofo/mappings",
        json={
            "source_domain": "labour_market",
            "matched_text": "Mining Engineer",
            "version": "2021",
        },
    )
    assert title_only.status_code == 201, title_only.text
    probe = title_only.json()
    assert probe["mapping_status"] == "deferred"
    assert probe["method"] == "title_only_probe"
    assert probe["title_only"] is True
    assert probe["ofo_code"] is None

    refused = client.post(
        f"/api/v1/dhet-ofo/mappings/{probe['mapping_id']}/review",
        json={
            "decision": "approved",
            "note": "Attempt to approve a title-only probe with a fabricated code",
            "selected_ofo_code": "121301",
        },
    )
    assert refused.status_code == 400
    assert "title-only" in refused.json()["detail"].lower()

    deferred = client.post(
        f"/api/v1/dhet-ofo/mappings/{probe['mapping_id']}/review",
        json={
            "decision": "deferred",
            "note": "Title-only evidence; deferred until full duties and skills evidence is supplied",
        },
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["mapping_status"] == "deferred"

    events = (
        sqlite_db.query(OFOEvidenceMappingReviewEvent)
        .filter(OFOEvidenceMappingReviewEvent.mapping_id == uuid.UUID(probe["mapping_id"]))
        .all()
    )
    assert [event.decision for event in events] == ["deferred"]

    stats = client.get("/api/v1/dhet-ofo/stats")
    assert stats.status_code == 200, stats.text
    assert stats.json()["mappings"]["title_only_probes"] == 1
    assert stats.json()["mappings"]["status_counts"].get("deferred") == 1


def test_unresolved_evidence_stays_deferred_with_reason(client, sqlite_db, evidence_dir):
    proposal = client.post(
        "/api/v1/dhet-ofo/mappings",
        json={
            "source_domain": "labour_market",
            "matched_text": "Specialised avant-garde artisan role description",
            "duties_text": "Curating bespoke kinetic installations for international biennales",
            "version": "2021",
        },
    )
    assert proposal.status_code == 201, proposal.text
    mapping = proposal.json()
    assert mapping["mapping_status"] == "deferred"
    assert mapping["ofo_code"] is None
    assert mapping["defer_reason"]


def test_stats_and_mapping_listing(client, sqlite_db, evidence_dir):
    _import_workflow(client)

    proposed = client.post(
        "/api/v1/dhet-ofo/mappings",
        json={
            "source_domain": "labour_market",
            "matched_text": "General Manager",
            "duties_text": "Plans and directs operations, manages budgets, leads production "
                           "teams and drives performance planning",
            "version": "2021",
        },
    )
    assert proposed.status_code == 201, proposed.text

    listed = client.get("/api/v1/dhet-ofo/mappings")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["mapping_id"] == proposed.json()["mapping_id"]

    stats = client.get("/api/v1/dhet-ofo/stats")
    body = stats.json()
    assert body["mappings"]["total"] == 1
    assert body["acquisition"]["import_summary"]["version"] == "2021"
    assert body["acquisition"]["occupation_counts_by_version"]["2021"] == 2
    assert body["enabled"] is True


# ------------------------------------------------------------------ breakdown
def test_breakdown_reconciles_by_code_length_and_acquisition(client, sqlite_db, evidence_dir):
    """The auditable breakdown must reconcile exactly: code-length buckets and
    per-acquisition lineage each sum to the displayed reference-table total."""
    _import_workflow(client)

    response = client.get("/api/v1/dhet-ofo/breakdown")
    assert response.status_code == 200, response.text
    body = response.json()

    # The workbook seeds one 2-digit group ("12") and one 6-digit occupation
    # ("121301"); both live in the ofo_occupation reference table.
    assert body["total_occupations_in_reference_tables"] == 2
    assert body["reconciles"] is True
    assert body["unattributed_rows"] == 0
    assert body["unclassified_codes"] == 0

    by_length = body["occupations_by_code_length"]
    assert by_length.get("sub_major_group") == 1
    assert by_length.get("occupation") == 1
    # code-length buckets sum exactly to the total
    assert sum(by_length.values()) == body["total_occupations_in_reference_tables"]

    acquisitions = body["occupations_by_acquisition"]
    assert len(acquisitions) == 1
    entry = acquisitions[0]
    assert entry["rows_present_now"] == 2
    assert entry["six_digit_rows_present_now"] == 1
    # imported_rows counts only six-digit occupations, so it matches the
    # six-digit presence and no misleading discrepancy note is raised.
    assert entry["rows_imported_at_import"] == 1
    assert "discrepancy_note" not in entry
    assert entry["versions"] == ["2021"]
    # acquisition buckets sum exactly to the total
    assert sum(a["rows_present_now"] for a in acquisitions) + body["unattributed_rows"] == (
        body["total_occupations_in_reference_tables"]
    )


def test_breakdown_empty_reference_table_reconciles_to_zero(client, sqlite_db, evidence_dir):
    """With no imports the breakdown still reconciles (0 == 0 == 0) rather than
    erroring, so the portal panel is always provable."""
    response = client.get("/api/v1/dhet-ofo/breakdown")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_occupations_in_reference_tables"] == 0
    assert body["reconciles"] is True
    assert body["occupations_by_acquisition"] == []
    assert body["unattributed_rows"] == 0