from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from app.services.model_evidence_service import ModelEvidenceService
from app.services.model_registry_service import ModelRegistryService


def test_perfect_probabilities_have_zero_calibration_error():
    service = ModelEvidenceService()
    truth = np.array([0] * 20 + [1] * 20)
    probability = truth.astype(float)
    evidence = service.classification_calibration(truth, probability)
    assert evidence["status"] == "passed"
    assert evidence["expected_calibration_error"] == 0.0
    assert evidence["brier_score"] == 0.0
    assert sum(row["count"] for row in evidence["reliability_bins"]) == 40


def test_small_holdout_cannot_make_calibration_claim():
    evidence = ModelEvidenceService().classification_calibration(
        [0, 1, 0, 1],
        [0.1, 0.9, 0.2, 0.8],
    )
    assert evidence["status"] == "insufficient_data"
    assert evidence["sample_count"] == 4


def test_model_card_is_complete_only_with_all_evidence_sections():
    service = ModelEvidenceService()
    metrics = {
        "reviewed_label_snapshot_id": "snapshot-1",
        "reviewed_label_snapshot_version": "labels-v1",
        "f1_score": 0.8,
        "baseline_comparisons": {"logistic_regression": {"f1_score": 0.7}},
        "calibration_evidence": {"status": "passed"},
        "fairness_audit": {"status": "passed", "limitations": ["Context groups only"]},
        "explainability": {"status": "passed", "global_shap_summary": [{"feature_name": "x"}]},
        "preprocessing_evidence": {"holdout_rows_used_during_fit": 0},
        "leakage_risks": ["Monitor evidence dates"],
        "target_definition": {"continuous_target": "reviewed label"},
    }
    complete = service.build_xgboost_model_card(
        model_version="xgb-1",
        dataset_fingerprint="a" * 64,
        metrics=metrics,
    )
    incomplete = service.build_xgboost_model_card(
        model_version="xgb-2",
        dataset_fingerprint="a" * 64,
        metrics={},
    )
    assert complete["status"] == "complete"
    assert complete["human_review_required"] is True
    assert incomplete["status"] == "incomplete"
    assert incomplete["completion_checks"]["calibration"] is False


def test_xgboost_promotion_gate_requires_passed_calibration_and_complete_card():
    registry = ModelRegistryService(MagicMock())
    entry = SimpleNamespace(
        model_type="xgboost",
        model_version="xgb-1",
        lifecycle_state="approved",
        snapshot_id="snapshot-1",
        dataset_fingerprint="a" * 64,
        artifact_path="candidate.pkl",
        artifact_checksum="b" * 64,
        artifact_size_bytes=128,
        metrics={
            "f1_score": 0.8,
            "cv_worst_f1": 0.7,
            "automated_tests": {"status": "passed", "summary": "passed"},
            "calibration_evidence": {"status": "insufficient_data", "sample_count": 8},
            "leakage_risks": [],
            "promotion_gate": {},
        },
        baseline_comparison={"logistic_regression": {"f1_score": 0.7}},
        cv_folds=[{"fold": 1, "f1": 0.7}],
        fairness_assessment={"status": "passed", "assessment_type": "contextual_subgroup_monitoring"},
        explainability={"feature_labels_verified": True, "global_shap_summary": [{"feature_name": "x"}]},
        model_card={"status": "complete", "intended_use": "Decision support"},
        promotion_gates={},
    )
    can_promote, gates = registry.can_promote(entry)
    assert can_promote is False
    assert gates["calibration"]["passed"] is False
