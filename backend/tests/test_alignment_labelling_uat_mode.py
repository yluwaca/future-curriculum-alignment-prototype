"""Offline tests for technical-UAT alignment review mode, sampling, snapshots, and XGBoost readiness.

Covers the model-review completion handoff (band 2/3):

1. ``generate_tasks`` records ``dataset_mode`` on every review task.
2. ``build_sample`` selects a deterministic stratified sample keyed by
   (subject code, demand band), records the sample seed/index and the two UAT
   reviewer personas in evidence metadata, and re-runs deterministically.
3. Queue filtering by dataset_mode/status/search/stratum.
4. Two distinct researcher-operated UAT reviewer identities label the same
   task; first/second personas are ``researcher_operated_uat`` (never
   ``independent_expert``).
5. Quality summary reports Cohen's kappa, a 5-level confusion matrix, per-subject
   distribution, and mode disaggregation.
6. Disagreement items list first/second reviews side by side for adjudication.
7. The locked label snapshot carries the UAT dataset mode, agreement
   statistics, sample definition, honest model-card provisions, and exports.
8. ``candidate_training_service.readiness`` reflects the locked snapshot state
   and marks technical-UAT snapshots ``experimental_uat`` (not independent
   expert validation).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.alignment_expert_label import AlignmentExpertLabel
from app.models.alignment_review_task import AlignmentReviewTask
from app.models.base import Base
from app.models.labour_market_signal import LabourMarketSignal
from app.services.alignment_labelling_service import alignment_labelling_service
from app.services.candidate_training_service import candidate_training_service
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service

MODE_UAT = "technical_uat_researcher_operated"
MODE_ASSISTED = "rule_assisted_confirmed"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


def _admin_user(identity_id: str = "e2e-alignment-admin") -> SimpleNamespace:
    return SimpleNamespace(
        identity_id=identity_id,
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


def _make_task(
    db,
    subject_code: str,
    demand_score: float,
    *,
    dataset_mode: str = MODE_UAT,
    status: str = "awaiting_first_review",
) -> AlignmentReviewTask:
    task = AlignmentReviewTask(
        document_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        chunk_id=None,
        evidence_window_hash=uuid.uuid4().hex,
        curriculum_evidence=(
            f"Subject {subject_code}: students will be able to analyse and design "
            "systems relevant to the labour market evidence window."
        ),
        labour_market_evidence=[{"demand_score": demand_score, "signal_id": str(uuid.uuid4())}],
        evidence_metadata={
            "subject_code": subject_code,
            "document_title": subject_code,
            "generated_by": "e2e-test",
        },
        dataset_mode=dataset_mode,
        status=status,
    )
    db.add(task)
    db.flush()
    return task


def _seed_six_tasks(db) -> list[AlignmentReviewTask]:
    return [
        _make_task(db, "ABC123", 0.85),
        _make_task(db, "ABC123", 0.20),
        _make_task(db, "DEF456", 0.75),
        _make_task(db, "DEF456", 0.10),
        _make_task(db, "GHI789", 0.60),
        _make_task(db, "GHI789", 0.55),
    ]


def test_rule_assisted_preview_confirm_and_lock_is_separate(sqlite_db):
    task = _make_task(sqlite_db, "ABC123", 0.85)
    task.curriculum_evidence = "Python programming is taught through Python projects and assessment."
    task.labour_market_evidence = [{"name": "Python", "demand_score": 0.85}]
    task.evidence_metadata = {**task.evidence_metadata, "target_skill": "Python"}
    sqlite_db.commit()

    preview = alignment_labelling_service.rule_assisted_proposals(sqlite_db, target_size=10)
    assert preview["selected_count"] == 1
    assert preview["items"][0]["proposed_label"] == 5
    dry_run = alignment_labelling_service.confirm_rule_assisted(
        sqlite_db,
        actor_id="e2e-alignment-admin",
        task_ids=[task.task_id],
        proposal_fingerprint=preview["proposal_fingerprint"],
        dry_run=True,
    )
    assert dry_run["selected_count"] == 1
    alignment_labelling_service.confirm_rule_assisted(
        sqlite_db,
        actor_id="e2e-alignment-admin",
        task_ids=[task.task_id],
        proposal_fingerprint=preview["proposal_fingerprint"],
        dry_run=False,
    )
    sqlite_db.refresh(task)
    assert task.dataset_mode == MODE_ASSISTED
    assert task.status == "completed"
    assert task.final_alignment_label == 5
    label = sqlite_db.query(AlignmentExpertLabel).filter_by(task_id=task.task_id).one()
    assert label.reviewer_persona == "rule_assisted_portal_confirmation"

    snapshot = label_dataset_snapshot_service.create_locked_snapshot(
        sqlite_db,
        actor_id="e2e-alignment-admin",
        dataset_mode=MODE_ASSISTED,
    )
    assert snapshot["row_count"] == 1
    assert snapshot["dataset_mode"] == MODE_ASSISTED
    assert snapshot["inclusion_rules"]["explicit_portal_confirmation_required"] is True


def _label(db, task: AlignmentReviewTask, reviewer_id: str, value: int) -> AlignmentExpertLabel:
    result = alignment_labelling_service.submit_label(
        db=db,
        task_id=task.task_id,
        reviewer_id=reviewer_id,
        alignment_label=value,
        confidence=4,
        justification="UAT verification of the reviewer workflow.",
        present_skills=[],
        missing_skills=[],
    )
    return result["label"]


# ================================================================== generate
def test_generate_tasks_records_dataset_mode(sqlite_db):
    signal = LabourMarketSignal(
        canonical_key="ops-and-it-professional",
        canonical_name="IT professionals",
        signal_type="labour_market",
        dimension_type="category",
        dimension_value="ops",
        year=2025,
        quarter="Q1",
        observed_value=100.0,
        normalised_value=1.0,
        demand_score=0.8,
        confidence_score=0.9,
        evidence_count=12,
        unit="normalised_posting_count",
        source_summary="test",
        signal_hash=uuid.uuid4().hex,
    )
    sqlite_db.add(signal)
    sqlite_db.commit()
    result = alignment_labelling_service.generate_tasks(
        sqlite_db, "e2e-agent", limit=10, dataset_mode=MODE_UAT
    )
    assert result["dataset_mode"] == MODE_UAT
    # no verified curriculum versions exist offline, so nothing is created
    assert result["created"] == 0
    assert result["eligible_versions"] == 0


# ================================================================== build_sample
def test_build_sample_is_deterministic_and_records_metadata(sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    seed = "uat-researcher-e2e-2026-09-12"
    first = alignment_labelling_service.build_sample(
        sqlite_db,
        actor_id="e2e-admin",
        dataset_mode=MODE_UAT,
        target_size=4,
        seed=seed,
    )
    second = alignment_labelling_service.build_sample(
        sqlite_db,
        actor_id="e2e-admin",
        dataset_mode=MODE_UAT,
        target_size=4,
        seed=seed,
    )
    assert first["selected_count"] == 4
    assert first["sample_seed"] == seed
    assert [item["task_id"] for item in first["selected_tasks"]] == [
        item["task_id"] for item in second["selected_tasks"]
    ]
    assert first["assigned_reviewers"] == ["uat_analyst_01", "uat_analyst_02"]
    selected_ids = {item["task_id"] for item in first["selected_tasks"]}
    for task in tasks:
        sample = (task.evidence_metadata or {}).get("sample") if task.task_id in selected_ids else None
        if task.task_id in selected_ids:
            assert sample["sample_seed"] == seed
            assert sample["sampling_policy"] == "deterministic_stratified_by_subject_and_demand_band"
            assert task.sample_seed == seed
            assert task.stratum and "|" in task.stratum
    # Every selected task has a distinct sample index within the selection.
    indexes = [item["sample_index"] for item in first["selected_tasks"]]
    assert sorted(indexes) == [1, 2, 3, 4]


def test_build_sample_rejects_unsupported_mode(sqlite_db):
    _seed_six_tasks(sqlite_db)
    with pytest.raises(ValueError):
        alignment_labelling_service.build_sample(
            sqlite_db, "e2e-admin", dataset_mode="not_a_mode", target_size=4
        )


# ================================================================== reviewers
def test_two_uat_reviewers_complete_and_persona_is_researcher_operated(sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    alignment_labelling_service.build_sample(
        sqlite_db, "e2e-admin", dataset_mode=MODE_UAT, target_size=4, seed="seed-x"
    )
    task = tasks[0]
    first = _label(sqlite_db, task, "uat_analyst_01", 4)
    assert first["reviewer_persona"] == "researcher_operated_uat"
    second = _label(sqlite_db, task, "uat_analyst_02", 4)
    assert second["reviewer_persona"] == "researcher_operated_uat"
    refreshed = sqlite_db.query(AlignmentReviewTask).get(task.task_id)
    assert refreshed.status == "completed"
    assert refreshed.final_alignment_label == 4
    # A reviewer must not relabel the same task.
    with pytest.raises(ValueError):
        alignment_labelling_service.submit_label(
            sqlite_db, task.task_id, "uat_analyst_01", 5, 4, "no", [], []
        )


def test_disagreement_routes_to_adjudication(sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    task = tasks[0]
    _label(sqlite_db, task, "uat_analyst_01", 2)
    _label(sqlite_db, task, "uat_analyst_02", 4)
    refreshed = sqlite_db.query(AlignmentReviewTask).get(task.task_id)
    assert refreshed.status == "adjudication_required"
    disagreements = alignment_labelling_service.disagreement_items(sqlite_db, dataset_mode=MODE_UAT)
    assert any(item["task_id"] == str(task.task_id) for item in disagreements)
    item = next(item for item in disagreements if item["task_id"] == str(task.task_id))
    assert item["first_review"]["alignment_label"] == 2
    assert item["second_review"]["alignment_label"] == 4
    third = _label(sqlite_db, task, "uat_adjudicator", 4)
    assert third["review_stage"] == "adjudication"
    refreshed = sqlite_db.query(AlignmentReviewTask).get(task.task_id)
    assert refreshed.status == "completed"
    assert refreshed.final_alignment_label == 4


# ================================================================== quality
def test_quality_summary_reports_kappa_and_confusion(sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    _label(sqlite_db, tasks[0], "uat_analyst_01", 4)
    _label(sqlite_db, tasks[0], "uat_analyst_02", 4)
    _label(sqlite_db, tasks[1], "uat_analyst_01", 3)
    _label(sqlite_db, tasks[1], "uat_analyst_02", 5)
    _label(sqlite_db, tasks[2], "uat_analyst_01", 2)
    _label(sqlite_db, tasks[2], "uat_analyst_02", 2)
    summary = alignment_labelling_service.quality_summary(sqlite_db)
    assert summary["paired_reviews"] == 3
    assert summary["agreements"] == 2
    assert summary["cohens_kappa"] is not None
    assert summary["kappa_interpretation"] is not None
    assert set(summary["confusion_matrix"]["labels"]) == {2, 3, 4, 5}
    assert summary["confusion_matrix"]["total"] == 3
    assert summary["dataset_modes"][MODE_UAT] == 6
    assert summary["per_subject_summary"]


# ================================================================== snapshot
def _complete_two_tasks(db) -> None:
    tasks = _seed_six_tasks(db)
    alignment_labelling_service.build_sample(
        db, "e2e-admin", dataset_mode=MODE_UAT, target_size=4, seed="lock-seed"
    )
    _label(db, tasks[0], "uat_analyst_01", 4)
    _label(db, tasks[0], "uat_analyst_02", 4)
    _label(db, tasks[1], "uat_analyst_01", 2)
    _label(db, tasks[1], "uat_analyst_02", 5)
    _label(db, tasks[1], "uat_adjudicator", 5)


def test_lock_snapshot_uat_mode_with_agreement_and_export(sqlite_db):
    tasks = _seed_six_tasks(db)
    alignment_labelling_service.build_sample(
        db, "e2e-admin", dataset_mode=MODE_UAT, target_size=4, seed="lock-seed"
    )
    _label(db, tasks[0], "uat_analyst_01", 4)
    _label(db, tasks[0], "uat_analyst_02", 4)
    _label(db, tasks[1], "uat_analyst_01", 2)
    _label(db, tasks[1], "uat_analyst_02", 5)
    _label(db, tasks[1], "uat_adjudicator", 5)


def test_lock_snapshot_uat_mode_with_agreement_and_export(sqlite_db):
    _complete_two_tasks(sqlite_db)
    staged = label_dataset_snapshot_service.create_locked_snapshot(
        db=sqlite_db,
        actor_id="e2e-admin",
        notes="UAT complete",
        dataset_mode=MODE_UAT,
    )
    # second identical lock reuses the exact same snapshot
    staged_again = label_dataset_snapshot_service.create_locked_snapshot(
        db=sqlite_db,
        actor_id="e2e-admin",
        notes="UAT complete",
        dataset_mode=MODE_UAT,
    )
    assert staged["snapshot_id"] == staged_again["snapshot_id"]
    assert staged["reused_identical_snapshot"] is False
    assert staged_again["reused_identical_snapshot"] is True
    assert staged["dataset_mode"] == MODE_UAT
    assert staged["row_count"] == 2
    assert staged["dataset_card"]["dataset_mode"] == MODE_UAT
    assert staged["dataset_card"]["independent_expert_validation"] is False
    assert "NOT independent expert labels" in staged["dataset_card"]["label_provenance"]
    assert staged["sample_definition"]["sample_seeds"] == ["lock-seed"]
    assert staged["sample_definition"]["reviewer_personas"] == ["researcher_operated_uat"]
    assert staged["agreement_statistics"]["paired_reviews"] == 2
    assert staged["agreement_statistics"]["cohens_kappa"] is not None
    assert staged["agreement_statistics"]["confusion_matrix"]["total"] == 2
    export = label_dataset_snapshot_service.export_snapshot(sqlite_db, staged["snapshot_id"])
    assert export["export_format"] == "json"
    assert len(export["records"]) == 2
    record_labels = {r["final_alignment_label"] for r in export["records"]}
    assert record_labels == {4, 5}


def test_readiness_reflects_locked_uat_snapshot(sqlite_db):
    no_snapshot = candidate_training_service.readiness(sqlite_db)
    assert no_snapshot["ready"] is False
    assert "No approved locked label dataset snapshot exists" in " ".join(no_snapshot["blocked_reasons"])
    _complete_two_tasks(sqlite_db)
    label_dataset_snapshot_service.create_locked_snapshot(
        db=sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT
    )
    report = candidate_training_service.readiness(sqlite_db)
    assert report["has_locked_label_snapshot"] is True
    assert report["dataset_mode"] == MODE_UAT
    assert report["experimental_uat"] is True
    assert report["independent_expert_validation"] is False
    # only 2 rows in the staged snapshot -> still blocked by the 10-row minimum
    assert report["ready"] is False
    assert any("at least 10 eligible rows" in reason for reason in report["blocked_reasons"])


# ================================================================== api wiring
def test_api_sample_endpoint_permissions_and_mode(client, sqlite_db):
    _seed_six_tasks(sqlite_db)
    response = client.post(
        "/api/v1/alignment-labels/tasks/sample",
        params={"target_size": 3, "dataset_mode": MODE_UAT, "sample_seed": "api-seed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dataset_mode"] == MODE_UAT
    assert body["selected_count"] == 3
    assert body["assigned_reviewers"] == ["uat_analyst_01", "uat_analyst_02"]
    bad = client.post(
        "/api/v1/alignment-labels/tasks/sample",
        params={"target_size": 3, "dataset_mode": "bogus_mode"},
    )
    assert bad.status_code == 422


def test_api_queue_filters(client, sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    _label(sqlite_db, tasks[0], "uat_analyst_01", 4)
    _label(sqlite_db, tasks[0], "uat_analyst_02", 4)
    response = client.get(
        "/api/v1/alignment-labels/tasks",
        params={"dataset_mode": MODE_UAT, "status": "awaiting_first_review"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["dataset_mode"] == MODE_UAT
    assert body["filters"]["status"] == "awaiting_first_review"
    assert body["items"]  # pending reviews are still routed


def test_api_ready_readiness_and_export(client, sqlite_db):
    _complete_two_tasks(sqlite_db)
    staged = label_dataset_snapshot_service.create_locked_snapshot(
        db=sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT
    )
    export = client.get(
        f"/api/v1/alignment-labels/snapshots/{staged['snapshot_id']}/export",
        params={"format": "csv"},
    )
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert "final_alignment_label" in export.text
    latest = client.get(
        "/api/v1/alignment-labels/snapshots/latest",
        params={"dataset_mode": MODE_UAT},
    )
    assert latest.status_code == 200
    assert latest.json()["latest"]["dataset_mode"] == MODE_UAT


# ================================================================== granularity
def test_generate_tasks_rejects_unknown_granularity(sqlite_db):
    with pytest.raises(ValueError):
        alignment_labelling_service.generate_tasks(
            sqlite_db, "e2e-agent", limit=10, dataset_mode=MODE_UAT, granularity="bogus"
        )


def test_generate_tasks_accepts_module_group_granularity(sqlite_db):
    # No verified curriculum versions offline -> nothing created, but the
    # granularity is accepted and echoed back rather than rejected.
    result = alignment_labelling_service.generate_tasks(
        sqlite_db, "e2e-agent", limit=10, dataset_mode=MODE_UAT,
        granularity="subject_module_group",
    )
    assert result["granularity"] == "subject_module_group_alignment"
    assert result["created"] == 0


# ================================================================== exclude_sampled
def test_build_sample_exclude_sampled_preserves_prior_sample(sqlite_db):
    tasks = _seed_six_tasks(sqlite_db)
    first = alignment_labelling_service.build_sample(
        sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT,
        target_size=3, seed="prior-sample",
    )
    prior_ids = {item["task_id"] for item in first["selected_tasks"]}
    prior_blocks = {
        t.task_id: dict((t.evidence_metadata or {}).get("sample") or {})
        for t in tasks if str(t.task_id) in prior_ids
    }
    # Build an additional sample over the remaining (unsampled) tasks without
    # disturbing the prior assignment.
    second = alignment_labelling_service.build_sample(
        sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT,
        target_size=3, seed="second-sample", exclude_sampled=True,
    )
    assert second["excluded_already_sampled"] == len(prior_ids)
    second_ids = {item["task_id"] for item in second["selected_tasks"]}
    assert second_ids.isdisjoint(prior_ids)
    # Prior sample blocks are byte-for-byte unchanged.
    for t in tasks:
        if str(t.task_id) in prior_ids:
            assert dict((t.evidence_metadata or {}).get("sample") or {}) == prior_blocks[t.task_id]
            assert t.sample_seed == "prior-sample"


def test_build_sample_default_reselects_same_tasks(sqlite_db):
    # Default (exclude_sampled=False) stays deterministic across re-runs.
    _seed_six_tasks(sqlite_db)
    a = alignment_labelling_service.build_sample(
        sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT,
        target_size=4, seed="stable",
    )
    b = alignment_labelling_service.build_sample(
        sqlite_db, actor_id="e2e-admin", dataset_mode=MODE_UAT,
        target_size=4, seed="stable",
    )
    assert [i["task_id"] for i in a["selected_tasks"]] == [i["task_id"] for i in b["selected_tasks"]]
    assert b["excluded_already_sampled"] == 0
