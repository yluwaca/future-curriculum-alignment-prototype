"""Regression tests for candidate isolation and controlled activation."""

from __future__ import annotations

from unittest.mock import MagicMock

import joblib

from app.services.model_service import ModelService


class PredictableCandidate:
    """Small serialisable classifier double used to validate activation."""

    classes_ = [0, 1]

    def predict_proba(self, rows):
        return [[0.25, 0.75] for _ in rows]


def _bare_service() -> ModelService:
    service = ModelService.__new__(ModelService)
    service.model_loader = MagicMock()
    service.xgboost_model = object()
    service.lstm_model = object()
    service.shap_explainer = None
    service.xgboost_loaded = False
    service.lstm_loaded = False
    service.xgboost_metrics = {}
    service.lstm_metrics = {}
    return service


def test_preparing_candidate_does_not_replace_serving_model(tmp_path, monkeypatch):
    artifact = tmp_path / "xgboost_candidate.pkl"
    joblib.dump(PredictableCandidate(), artifact)
    service = _bare_service()
    original_serving_model = service.xgboost_model
    monkeypatch.setattr(
        "app.services.model_service.shap.TreeExplainer",
        lambda model: ("explainer", model),
    )

    prepared = service.prepare_artifact_activation("xgboost", str(artifact))

    assert service.xgboost_model is original_serving_model
    assert prepared["model"] is not original_serving_model


def test_activation_swaps_only_the_selected_serving_reference(
    tmp_path,
    monkeypatch,
):
    artifact = tmp_path / "xgboost_candidate.pkl"
    joblib.dump(PredictableCandidate(), artifact)
    service = _bare_service()
    original_lstm = service.lstm_model
    monkeypatch.setattr(
        "app.services.model_service.shap.TreeExplainer",
        lambda model: ("explainer", model),
    )
    prepared = service.prepare_artifact_activation("xgboost", str(artifact))

    service.activate_prepared_artifact(prepared)

    assert service.xgboost_model is prepared["model"]
    assert service.xgboost_loaded is True
    assert service.lstm_model is original_lstm
    service.model_loader.clear_cache.assert_called_once_with()


def test_activation_installs_candidate_metrics_with_model(tmp_path, monkeypatch):
    artifact = tmp_path / "xgboost_candidate.pkl"
    joblib.dump(PredictableCandidate(), artifact)
    service = _bare_service()
    monkeypatch.setattr("app.services.model_service.shap.TreeExplainer", lambda model: None)
    prepared = service.prepare_artifact_activation("xgboost", str(artifact))
    prepared["metrics"] = {
        "feature_names": ["curriculum_character_count"],
        "operating_threshold": 0.35,
    }

    service.activate_prepared_artifact(prepared)

    assert service.xgboost_metrics == prepared["metrics"]


def test_xgboost_canary_validates_persisted_serving_contract():
    prepared = {"model_type": "xgboost", "model": PredictableCandidate()}
    metrics = {
        "serving_feature_contract": {
            "contract_id": "reviewed_alignment_lexical_v1",
            "selected_columns": ["curriculum_character_count"],
            "operating_threshold": 0.35,
        }
    }

    result = ModelService.canary_prediction(prepared, metrics)

    assert result["status"] == "passed"
