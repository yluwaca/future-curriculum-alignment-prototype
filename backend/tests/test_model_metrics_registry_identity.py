"""Tests for the read-time registry-identity enrichment of /predictive/model-metrics.

Covers the S4 'legacy failed-job presentation' fix: the persisted metrics file is
written by the trainer before candidate_training_service attaches the registry
identity, so lifecycle_state / dataset_mode / experimental_uat are absent on disk.
`_attach_registry_identity` joins the persisted dataset_fingerprint to the model
registry at read time (never rewriting model_metrics.json) so the successful
candidate and its exact fingerprint are unambiguous, while historical failures stay
visible and every prior candidate remains append-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.model_registry import ModelRegistryEntry
from app.routers.predictive import _attach_registry_identity


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def sqlite_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _entry(db, model_type, fingerprint, state="candidate", version="v1", metrics=None, trained=None):
    e = ModelRegistryEntry(
        entry_id=uuid.uuid4(),
        model_type=model_type,
        model_version=version,
        lifecycle_state=state,
        artifact_path="/tmp/x.pkl",
        dataset_fingerprint=fingerprint,
        snapshot_id=uuid.uuid4(),
        trained_at=trained or datetime.now(timezone.utc),
        metrics=metrics or {},
        is_active=0,
    )
    db.add(e)
    db.commit()
    return e


FP = "f0c6c183c934d8e41cf49f5f991ea1b0396f40fe3e976e11a4266ab787d90480"


def test_fingerprint_match_surfaces_candidate_identity(sqlite_db):
    _entry(
        sqlite_db, "xgboost", FP, state="candidate", version="xgboost-20260912T052559",
        metrics={
            "dataset_mode": "technical_uat_researcher_operated",
            "experimental_uat": True,
            "label_provenance": "researcher_operated_uat_accounts_uq58x_untrusted",
            "reviewed_label_snapshot_version": "alignment_labels_20260912_052100",
        },
    )
    metrics = {"xgboost": {"dataset_fingerprint": FP, "f1_score": 0.0}}
    out = _attach_registry_identity(sqlite_db, metrics)
    ident = out["xgboost"]["registry_identity"]
    assert ident["matched"] is True
    assert ident["matched_on"] == "dataset_fingerprint"
    assert ident["fingerprint_matches_metrics"] is True
    assert ident["lifecycle_state"] == "candidate"
    assert ident["is_active"] is False
    assert ident["experimental_uat"] is True
    # top-level disclosure surfaced so the panel cannot hide experimental-UAT status
    assert out["xgboost"]["dataset_mode"] == "technical_uat_researcher_operated"
    assert out["xgboost"]["experimental_uat"] is True
    assert out["xgboost"]["lifecycle_state"] == "candidate"
    assert out["xgboost"]["registry_entry_id"]


def test_fallback_to_latest_candidate_when_fingerprint_absent(sqlite_db):
    _entry(sqlite_db, "lstm", "other-fingerprint", state="candidate", version="lstm-1")
    metrics = {"lstm": {"rmse": 0.985}}  # no dataset_fingerprint on disk
    out = _attach_registry_identity(sqlite_db, metrics)
    ident = out["lstm"]["registry_identity"]
    assert ident["matched"] is True
    assert ident["matched_on"] == "latest_candidate_fallback"
    assert ident["fingerprint_matches_metrics"] is False


def test_fingerprint_mismatch_falls_back_and_flags(sqlite_db):
    _entry(sqlite_db, "xgboost", "registry-fp", state="candidate", version="xgboost-1")
    metrics = {"xgboost": {"dataset_fingerprint": "different-fp"}}
    out = _attach_registry_identity(sqlite_db, metrics)
    ident = out["xgboost"]["registry_identity"]
    # no exact match -> latest candidate fallback, explicitly flagged as not matching
    assert ident["matched"] is True
    assert ident["matched_on"] == "latest_candidate_fallback"
    assert ident["fingerprint_matches_metrics"] is False


def test_no_registry_entry_reports_unmatched(sqlite_db):
    metrics = {"xgboost": {"dataset_fingerprint": FP, "f1_score": 0.0}}
    out = _attach_registry_identity(sqlite_db, metrics)
    ident = out["xgboost"]["registry_identity"]
    assert ident["matched"] is False
    assert "No registry candidate" in ident["reason"]
    # lifecycle_state must NOT be fabricated when there is no registry entry
    assert "lifecycle_state" not in out["xgboost"]


def test_empty_and_missing_blocks_are_skipped(sqlite_db):
    _entry(sqlite_db, "xgboost", FP, state="candidate")
    metrics = {"xgboost": None, "lstm": {}, "readiness": {"ready": True}}
    out = _attach_registry_identity(sqlite_db, metrics)
    assert out["xgboost"] is None
    assert out["lstm"] == {}
    assert "registry_identity" not in out["lstm"]
    # unrelated keys are preserved untouched
    assert out["readiness"] == {"ready": True}


def test_enrichment_is_non_destructive_to_persisted_metrics(sqlite_db):
    _entry(sqlite_db, "xgboost", FP, state="candidate", metrics={"experimental_uat": True})
    metrics = {"xgboost": {"dataset_fingerprint": FP, "f1_score": 0.0, "roc_auc": 0.5}}
    out = _attach_registry_identity(sqlite_db, metrics)
    # original metric values are preserved (enrichment only adds identity fields)
    assert out["xgboost"]["f1_score"] == 0.0
    assert out["xgboost"]["roc_auc"] == 0.5
    assert out["xgboost"]["dataset_fingerprint"] == FP
