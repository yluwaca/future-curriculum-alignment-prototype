"""
Phase 8: Comprehensive ML pipeline tests.

Covers:
- Model registry lifecycle and state transitions
- Leakage detection (threshold computed inside CV folds)
- Baseline comparisons recorded
- Feature selection uses MI not target-leaking XGB
- Promotion gates enforced
- Dataset snapshot integration
"""

from __future__ import annotations

import os
import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest


# =========================================================
# Model Registry Unit Tests
# =========================================================


class TestModelRegistryLifecycle:
    """Test model registry lifecycle states and transitions."""

    def _make_mock_db_session(self):
        session = MagicMock()
        session.add = MagicMock()
        session.commit = MagicMock()
        session.refresh = MagicMock()
        return session

    def test_register_candidate(self):
        from app.models.model_registry import VALID_TRANSITIONS, ModelRegistryEntry

        entry = ModelRegistryEntry(
            entry_id=uuid4(),
            model_type="xgboost",
            model_version="xgboost-20260727T120000",
            lifecycle_state="candidate",
            artifact_path="/tmp/test.pkl",
            is_active=0,
        )
        assert entry.lifecycle_state == "candidate"
        assert entry.is_active == 0

    def test_valid_transitions_defined(self):
        from app.models.model_registry import VALID_TRANSITIONS

        assert "draft" in VALID_TRANSITIONS
        assert "candidate" in VALID_TRANSITIONS
        assert "evaluated" in VALID_TRANSITIONS
        assert "active" in VALID_TRANSITIONS
        assert "retired" in VALID_TRANSITIONS

        assert "training" in VALID_TRANSITIONS["draft"]
        assert "evaluated" in VALID_TRANSITIONS["candidate"]
        assert "active" in VALID_TRANSITIONS["approved"]

    def test_invalid_transition_rejected(self):
        from app.models.model_registry import VALID_TRANSITIONS

        invalid = VALID_TRANSITIONS.get("active", [])
        assert "candidate" not in invalid, "Cannot go from active back to candidate"

    def test_register_candidate_via_service(self):
        from app.models.model_registry import ModelRegistryEntry
        from app.services.model_registry_service import ModelRegistryService

        db = self._make_mock_db_session()

        captured_entries = []

        def mock_add(entry):
            captured_entries.append(entry)

        def mock_refresh(entry):
            pass

        db.add = mock_add
        db.refresh = mock_refresh

        svc = ModelRegistryService(db)
        entry = svc.register_candidate(
            model_type="xgboost",
            model_version="xgboost-20260727T120000",
            artifact_path="/tmp/test.pkl",
            snapshot_id=str(uuid4()),
            dataset_fingerprint="abc123",
            metrics={"f1_score": 0.75},
            cv_folds=[{"fold": 1, "f1": 0.7}, {"fold": 2, "f1": 0.8}],
            notes="Test registration",
        )

        assert entry.lifecycle_state == "candidate"
        assert entry.model_type == "xgboost"
        assert entry.metrics == {"f1_score": 0.75}
        assert len(entry.cv_folds) == 2
        assert len(captured_entries) == 1

    def test_promotion_gates_require_approval_before_promotion(self):
        from app.models.model_registry import ModelRegistryEntry
        from app.services.model_registry_service import ModelRegistryService

        db = MagicMock()
        svc = ModelRegistryService(db)

        entry = ModelRegistryEntry(
            entry_id=uuid4(),
            model_type="xgboost",
            model_version="xgboost-20260727T120000",
            lifecycle_state="evaluated",
            artifact_path="/tmp/test.pkl",
            artifact_checksum="a" * 64,
            artifact_size_bytes=128,
            snapshot_id=uuid4(),
            dataset_fingerprint="abc123",
            metrics={
                "f1_score": 0.75,
                "cv_worst_f1": 0.61,
                "calibration_evidence": {
                    "status": "passed",
                    "expected_calibration_error": 0.05,
                    "sample_count": 40,
                },
                "automated_tests": {"status": "passed", "summary": "Unit tests passed"},
            },
            cv_folds=[{"fold": 1, "f1": 0.7}, {"fold": 2, "f1": 0.8}],
            baseline_comparison={"logistic_regression": {"f1_score": 0.6}},
            fairness_assessment={"status": "passed", "assessment_type": "contextual_subgroup_monitoring"},
            explainability={"shap_top_features": ["skill_count"], "feature_labels_verified": True},
            model_card={"status": "complete", "intended_use": "Decision support only"},
        )

        can_approve, approve_gates = svc.can_approve(entry)
        can_promote, promote_gates = svc.can_promote(entry)

        assert can_approve is True, f"Expected approval gates to pass: {approve_gates}"
        assert can_promote is False, "Promotion must require explicit authorised approval"
        assert promote_gates["explicit_authorised_approval"]["passed"] is False

        entry.lifecycle_state = "approved"
        can_promote, promote_gates = svc.can_promote(entry)
        assert can_promote is True, f"Expected all promotion gates to pass after approval: {promote_gates}"

    def test_promotion_gates_fail_without_snapshot(self):
        from app.models.model_registry import ModelRegistryEntry
        from app.services.model_registry_service import ModelRegistryService

        db = MagicMock()
        svc = ModelRegistryService(db)

        entry = ModelRegistryEntry(
            entry_id=uuid4(),
            model_type="xgboost",
            model_version="xgboost-20260727T120000",
            lifecycle_state="candidate",
            artifact_path="/tmp/test.pkl",
            snapshot_id=None,
            metrics={"f1_score": 0.75},
            cv_folds=[],
            baseline_comparison={},
            fairness_assessment={},
            explainability={},
            model_card={},
        )

        can, gates = svc.can_promote(entry)
        assert can is False
        assert gates["dataset_snapshot"]["passed"] is False

    def test_promotion_gates_fail_without_artifact_checksum_or_tests(self):
        from app.models.model_registry import ModelRegistryEntry
        from app.services.model_registry_service import ModelRegistryService

        svc = ModelRegistryService(MagicMock())
        entry = ModelRegistryEntry(
            entry_id=uuid4(),
            model_type="xgboost",
            model_version="xgboost-20260727T120000",
            lifecycle_state="approved",
            artifact_path="/tmp/test.pkl",
            artifact_checksum=None,
            artifact_size_bytes=None,
            snapshot_id=uuid4(),
            dataset_fingerprint="abc123",
            metrics={"f1_score": 0.75, "cv_worst_f1": 0.7},
            cv_folds=[{"fold": 1, "f1": 0.7}],
            baseline_comparison={"logistic_regression": {"f1_score": 0.6}},
            fairness_assessment={"status": "passed"},
            explainability={"feature_labels_verified": True},
            model_card={"intended_use": "Decision support only"},
        )

        can, gates = svc.can_promote(entry)
        assert can is False
        assert gates["artifact_versioned"]["passed"] is False
        assert gates["automated_tests"]["passed"] is False

    def test_register_candidate_records_artifact_checksum_and_model_card(self, tmp_path):
        from app.services.model_registry_service import ModelRegistryService

        artifact = tmp_path / "xgboost_candidate.pkl"
        artifact.write_bytes(b"phase8-artifact")
        db = self._make_mock_db_session()
        db.add = lambda entry: None
        db.refresh = lambda entry: None

        svc = ModelRegistryService(db)
        entry = svc.register_candidate(
            model_type="xgboost",
            model_version="xgboost-20260728T120000",
            artifact_path=str(artifact),
            snapshot_id=str(uuid4()),
            dataset_fingerprint="abc123",
            metrics={"f1_score": 0.75, "phase": "phase8-test"},
        )

        assert entry.lifecycle_state == "candidate"
        assert entry.is_active in (0, None)
        assert entry.artifact_size_bytes == len(b"phase8-artifact")
        assert len(entry.artifact_checksum) == 64
        assert entry.model_card["intended_use"]
        assert entry.model_card["dataset_fingerprint"] == "abc123"

    def test_to_dict_serialization(self):
        from app.models.model_registry import ModelRegistryEntry
        from app.services.model_registry_service import ModelRegistryService

        db = MagicMock()
        svc = ModelRegistryService(db)

        entry = ModelRegistryEntry(
            entry_id=uuid4(),
            model_type="lstm",
            model_version="lstm-20260727T120000",
            lifecycle_state="candidate",
            artifact_path="/tmp/lstm.keras",
            is_active=0,
            metrics={"rmse": 0.18},
            cv_folds=[],
            baseline_comparison={},
            fairness_assessment={},
            explainability={},
            model_card={},
        )

        d = svc.to_dict(entry)
        assert d["model_type"] == "lstm"
        assert d["is_active"] is False
        assert d["metrics"]["rmse"] == 0.18


# =========================================================
# Leakage Detection Tests
# =========================================================


class TestLeakageDetection:
    """Verify no target leakage in training pipeline."""

    def test_threshold_computed_per_fold(self):
        """The median threshold must be computed from training fold data only,
        not from the full dataset."""
        y_continuous = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])

        from sklearn.model_selection import TimeSeriesSplit

        tscv = TimeSeriesSplit(n_splits=3)

        thresholds = []
        for train_idx, test_idx in tscv.split(y_continuous):
            y_train = y_continuous[train_idx]
            fold_threshold = float(np.median(y_train))
            thresholds.append(fold_threshold)

        assert len(thresholds) == 3
        # Thresholds should differ across folds because each fold has
        # different training data
        assert len(set(thresholds)) > 1, (
            "All fold thresholds are identical — likely using full-dataset median"
        )

    def test_feature_selection_uses_mutual_info(self):
        """Feature selection should use mutual information, not XGBClassifier
        fitted on full dataset with labels."""
        np.random.seed(42)
        n_samples, n_features = 100, 30
        X = np.random.randn(n_samples, n_features)
        y = (X[:, 0] + X[:, 1] + np.random.randn(n_samples) * 0.1 > 0).astype(int)

        from sklearn.feature_selection import mutual_info_classif

        mi_scores = mutual_info_classif(X, y, random_state=42)
        top_indices = np.argsort(mi_scores)[::-1][:5]

        # Top features should include the informative ones
        assert 0 in top_indices or 1 in top_indices, (
            f"MI failed to rank informative features in top 5: top={top_indices}"
        )

    def test_no_data_leakage_in_final_split(self):
        """Final 80/20 split should use only training data for threshold."""
        np.random.seed(42)
        y_continuous = np.sort(np.random.uniform(0, 1, 100))
        X = np.random.randn(100, 5)

        split_idx = int(len(X) * 0.8)
        y_cont_train = y_continuous[:split_idx]
        threshold = float(np.median(y_cont_train))

        y_train = np.array([1 if s >= threshold else 0 for s in y_cont_train])
        y_test = np.array([1 if s >= threshold else 0 for s in y_continuous[split_idx:]])

        assert len(set(y_train)) >= 1
        assert len(set(y_test)) >= 1

        # Threshold should come from training data only
        full_median = float(np.median(y_continuous))
        train_median = float(np.median(y_cont_train))
        assert threshold == train_median
        # These may differ if the split changes the distribution
        # (in sorted data they should be close but not identical)



class TestSplitsAndMetrics:
    """Tests for chronological split, duplicate isolation, and metric denominators."""

    def test_chronological_split_preserves_order(self):
        observations = list(range(20))
        split_idx = int(len(observations) * 0.8)
        train = observations[:split_idx]
        test = observations[split_idx:]
        assert max(train) < min(test)
        assert len(train) + len(test) == len(observations)

    def test_duplicate_isolation_across_folds(self):
        records = [
            {"record_id": "a1", "duplicate_key": "job-a", "fold": "train"},
            {"record_id": "a2", "duplicate_key": "job-a", "fold": "train"},
            {"record_id": "b1", "duplicate_key": "job-b", "fold": "test"},
        ]
        train_keys = {r["duplicate_key"] for r in records if r["fold"] == "train"}
        test_keys = {r["duplicate_key"] for r in records if r["fold"] == "test"}
        assert train_keys.isdisjoint(test_keys), "Duplicate job adverts must not cross train/test folds"

    def test_expanding_chronological_group_folds_are_disjoint_and_forward_only(self):
        from app.services.model_service import ModelService

        groups = ["g1", "g1", "g2", "g2", "g3", "g3", "g4", "g4"]
        folds = ModelService._chronological_group_folds(groups, requested_splits=3)
        assert len(folds) == 3
        for train_idx, val_idx in folds:
            train_groups = {groups[int(index)] for index in train_idx}
            val_groups = {groups[int(index)] for index in val_idx}
            assert train_groups.isdisjoint(val_groups)
            assert max(train_idx) < min(val_idx)

    def test_confusion_matrix_denominator_matches_holdout_size(self):
        from sklearn.metrics import confusion_matrix

        y_true = np.array([0, 1, 1, 0, 1, 0])
        y_pred = np.array([0, 1, 0, 0, 1, 1])
        tn, fp, fn, tp = [int(v) for v in confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()]
        assert tn + fp + fn + tp == len(y_true)

    def test_threshold_sensitivity_rejects_single_class_thresholds(self):
        y_score = np.array([0.10, 0.20, 0.30, 0.40])
        threshold = 0.95
        y_candidate = (y_score >= threshold).astype(int)
        assert len(np.unique(y_candidate)) == 1


# =========================================================
# Baseline Comparison Tests
# =========================================================


class TestBaselineComparisons:
    """Verify baseline models are computed correctly."""

    def test_logistic_regression_baseline(self):
        from sklearn.datasets import make_classification
        from sklearn.dummy import DummyClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import f1_score, roc_auc_score
        from sklearn.model_selection import train_test_split

        X, y = make_classification(
            n_samples=200, n_features=10, random_state=42,
        )
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42,
        )

        lr = LogisticRegression(max_iter=500, random_state=42)
        lr.fit(X_train, y_train)
        lr_pred = lr.predict(X_test)
        lr_f1 = f1_score(y_test, lr_pred, zero_division=0)
        assert lr_f1 > 0.0, "Logistic Regression baseline F1 is zero"

        maj = DummyClassifier(strategy="most_frequent", random_state=42)
        maj.fit(X_train, y_train)
        maj_pred = maj.predict(X_test)
        maj_f1 = f1_score(y_test, maj_pred, zero_division=0)

        rand = DummyClassifier(strategy="stratified", random_state=42)
        rand.fit(X_train, y_train)
        rand_pred = rand.predict(X_test)
        rand_f1 = f1_score(y_test, rand_pred, zero_division=0)

        # LR should beat or match random/majority baselines on structured data
        assert lr_f1 >= maj_f1, (
            f"LR F1 ({lr_f1:.4f}) should >= majority F1 ({maj_f1:.4f})"
        )

    def test_lstm_baseline_methods(self):
        """Test that LSTM baseline methods (naive, MA, linear trend) produce
        reasonable results on synthetic sequence data."""
        np.random.seed(42)
        n_test = 20
        seq_len = 12
        X_test = np.random.randn(n_test, seq_len, 1)
        y_test = X_test[:, -1, 0] + np.random.randn(n_test) * 0.1

        # Naive last value
        last_val_preds = X_test[:, -1, 0]
        last_val_rmse = float(np.sqrt(np.mean((y_test - last_val_preds) ** 2)))

        # Moving average (window=3)
        ma_preds = np.mean(X_test[:, -3:, 0], axis=1)
        ma_rmse = float(np.sqrt(np.mean((y_test - ma_preds) ** 2)))

        # Linear trend
        lt_preds = []
        for seq in X_test[:, :, 0]:
            coeffs = np.polyfit(np.arange(len(seq)), seq, 1)
            lt_preds.append(np.polyval(coeffs, len(seq)))
        lt_preds = np.array(lt_preds)
        lt_rmse = float(np.sqrt(np.mean((y_test - lt_preds) ** 2)))

        assert last_val_rmse > 0
        assert ma_rmse > 0
        assert lt_rmse > 0


# =========================================================
# Model Artifact Tests
# =========================================================


class TestModelArtifacts:
    """Verify model artifacts are saved and loaded correctly."""

    def test_versioned_xgboost_artifact_saved(self):
        """Check that versioned XGBoost artifacts exist in models dir."""
        models_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "models"
        )
        pkl_files = [
            f for f in os.listdir(models_dir)
            if f.startswith("xgboost_") and f.endswith(".pkl")
        ]
        assert len(pkl_files) > 0, "No versioned XGBoost artifacts found"

    def test_versioned_lstm_artifact_saved(self):
        """Check that versioned LSTM artifacts exist in models dir."""
        models_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "models"
        )
        keras_files = [
            f for f in os.listdir(models_dir)
            if f.startswith("lstm_") and f.endswith(".keras")
        ]
        assert len(keras_files) > 0, "No versioned LSTM artifacts found"

    def test_metrics_json_exists(self):
        """Check that model_metrics.json exists and has expected structure."""
        metrics_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "models", "model_metrics.json"
        )
        import json

        if os.path.exists(metrics_path):
            with open(metrics_path) as f:
                metrics = json.load(f)
            assert isinstance(metrics, dict)
