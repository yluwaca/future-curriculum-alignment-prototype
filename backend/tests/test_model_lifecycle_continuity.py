from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import joblib

from app.services.model_lifecycle_coordinator import ModelLifecycleCoordinator
from app.services.model_registry_service import ModelRegistryService
from app.services.model_service import ModelService


class CanaryClassifier:
    classes_ = [0, 1]

    def __init__(self, positive_probability: float):
        self.positive_probability = positive_probability

    def predict_proba(self, rows):
        return [
            [1.0 - self.positive_probability, self.positive_probability]
            for _ in rows
        ]


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if isinstance(self.result, list):
            return self.result[0] if self.result else None
        return self.result

    def all(self):
        return self.result if isinstance(self.result, list) else [self.result]


class FakeDb:
    def __init__(self, query_results, fail_commit=False):
        self.query_results = list(query_results)
        self.fail_commit = fail_commit
        self.rolled_back = False
        self.committed = False

    def query(self, *args, **kwargs):
        return FakeQuery(self.query_results.pop(0))

    def flush(self):
        return None

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("simulated commit failure")
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, entry):
        return None


def _bare_model_service() -> ModelService:
    service = ModelService.__new__(ModelService)
    service.model_loader = MagicMock()
    service.xgboost_model = CanaryClassifier(0.2)
    service.lstm_model = None
    service.shap_explainer = "old-explainer"
    service.xgboost_loaded = True
    service.lstm_loaded = False
    return service


def _artifact(probability: float) -> tuple[str, str]:
    directory = Path.cwd() / ".lifecycle-test-artifacts"
    directory.mkdir(exist_ok=True)
    path = directory / f"{uuid4()}.pkl"
    joblib.dump(CanaryClassifier(probability), path)
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _entry(version: str, probability: float, state: str, active: int):
    path, checksum = _artifact(probability)
    return SimpleNamespace(
        entry_id=uuid4(),
        model_type="xgboost",
        model_version=version,
        lifecycle_state=state,
        is_active=active,
        artifact_path=path,
        artifact_checksum=checksum,
        artifact_size_bytes=Path(path).stat().st_size,
        metrics={"feature_names": ["a", "b"]},
        promoted_at=None,
        promoted_by=None,
        retired_at=None,
    )


def test_promotion_changes_registry_and_known_canary_together(monkeypatch):
    service = _bare_model_service()
    coordinator = ModelLifecycleCoordinator(service)
    candidate = _entry("candidate-v2", 0.8, "approved", 0)
    previous = _entry("active-v1", 0.2, "active", 1)
    db = FakeDb([candidate, [previous]])
    monkeypatch.setattr(ModelRegistryService, "can_promote", lambda self, entry: (True, {}))
    monkeypatch.setattr("app.services.model_service.shap.TreeExplainer", lambda model: "new-explainer")

    promoted = coordinator.promote(db, candidate.entry_id, "admin")

    assert db.committed is True
    assert promoted.is_active == 1
    assert previous.lifecycle_state == "retired"
    assert service.xgboost_model.predict_proba([[0.0, 0.0]])[0][1] == 0.8
    assert promoted.metrics["activation_evidence"]["canary"]["status"] == "passed"


def test_commit_failure_restores_previous_serving_reference(monkeypatch):
    service = _bare_model_service()
    original = service.xgboost_model
    coordinator = ModelLifecycleCoordinator(service)
    candidate = _entry("candidate-v2", 0.8, "approved", 0)
    db = FakeDb([candidate, []], fail_commit=True)
    monkeypatch.setattr(ModelRegistryService, "can_promote", lambda self, entry: (True, {}))
    monkeypatch.setattr("app.services.model_service.shap.TreeExplainer", lambda model: "new-explainer")

    try:
        coordinator.promote(db, candidate.entry_id, "admin")
        assert False, "Expected simulated commit failure"
    except RuntimeError:
        pass

    assert db.rolled_back is True
    assert service.xgboost_model is original
    assert service.xgboost_model.predict_proba([[0.0, 0.0]])[0][1] == 0.2


def test_restart_restores_only_registry_designated_active_artifact(monkeypatch):
    service = _bare_model_service()
    coordinator = ModelLifecycleCoordinator(service)
    active = _entry("active-v3", 0.7, "active", 1)
    db = FakeDb([[active], []])
    monkeypatch.setattr("app.services.model_service.shap.TreeExplainer", lambda model: "restored-explainer")

    result = coordinator.restore_active_models(db)

    assert result["status"] == "passed"
    assert result["models"]["xgboost"]["model_version"] == "active-v3"
    assert result["models"]["lstm"]["status"] == "no_active_registry_model"
    assert service.xgboost_model.predict_proba([[0.0, 0.0]])[0][1] == 0.7
    assert service.lstm_loaded is False


def test_rollback_restores_retired_model_and_canary(monkeypatch):
    service = _bare_model_service()
    coordinator = ModelLifecycleCoordinator(service)
    current = _entry("active-v2", 0.8, "active", 1)
    retired = _entry("retired-v1", 0.3, "retired", 0)
    db = FakeDb([current, retired])
    monkeypatch.setattr("app.services.model_service.shap.TreeExplainer", lambda model: "rollback-explainer")

    restored = coordinator.rollback(db, "xgboost", "admin")

    assert db.committed is True
    assert current.lifecycle_state == "retired"
    assert restored.lifecycle_state == "active"
    assert restored.metrics["activation_evidence"]["action"] == "rollback"
    assert service.xgboost_model.predict_proba([[0.0, 0.0]])[0][1] == 0.3
