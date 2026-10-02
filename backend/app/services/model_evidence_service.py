"""Research and governance evidence for supervised model candidates."""

from __future__ import annotations

from typing import Any, Dict, Iterable

import numpy as np


class ModelEvidenceService:
    MIN_CALIBRATION_ROWS = 30
    MAX_ACCEPTABLE_ECE = 0.10

    def classification_calibration(
        self,
        y_true: Iterable[int],
        y_probability: Iterable[float],
        bins: int = 10,
    ) -> Dict[str, Any]:
        truth = np.asarray(list(y_true), dtype=int)
        probability = np.clip(np.asarray(list(y_probability), dtype=float), 0.0, 1.0)
        if len(truth) != len(probability):
            raise ValueError("Calibration labels and probabilities must have equal length")
        if not len(truth):
            return self._insufficient_calibration(0, "No holdout predictions")

        edges = np.linspace(0.0, 1.0, max(2, int(bins)) + 1)
        bin_ids = np.minimum(np.digitize(probability, edges[1:-1], right=False), len(edges) - 2)
        rows = []
        weighted_gap = 0.0
        max_gap = 0.0
        for index in range(len(edges) - 1):
            mask = bin_ids == index
            count = int(mask.sum())
            if not count:
                continue
            mean_probability = float(probability[mask].mean())
            observed_rate = float(truth[mask].mean())
            gap = abs(mean_probability - observed_rate)
            weighted_gap += gap * count
            max_gap = max(max_gap, gap)
            rows.append(
                {
                    "bin": index + 1,
                    "lower": float(edges[index]),
                    "upper": float(edges[index + 1]),
                    "count": count,
                    "mean_probability": mean_probability,
                    "observed_positive_rate": observed_rate,
                    "absolute_gap": float(gap),
                }
            )

        ece = float(weighted_gap / len(truth))
        brier = float(np.mean((probability - truth) ** 2))
        sufficient = len(truth) >= self.MIN_CALIBRATION_ROWS and len(np.unique(truth)) == 2
        passed = sufficient and ece <= self.MAX_ACCEPTABLE_ECE
        status = "passed" if passed else ("review_required" if sufficient else "insufficient_data")
        return {
            "status": status,
            "method": "equal_width_reliability_bins",
            "sample_count": int(len(truth)),
            "positive_count": int(truth.sum()),
            "negative_count": int(len(truth) - truth.sum()),
            "expected_calibration_error": ece,
            "maximum_calibration_error": float(max_gap),
            "brier_score": brier,
            "acceptance_threshold": {
                "minimum_holdout_rows": self.MIN_CALIBRATION_ROWS,
                "maximum_expected_calibration_error": self.MAX_ACCEPTABLE_ECE,
                "both_classes_required": True,
            },
            "reliability_bins": rows,
            "limitations": [
                "Calibration is estimated on the untouched chronological holdout only.",
                "Small or single-class holdouts cannot support a calibration claim.",
                "Calibration must be monitored after deployment as evidence distributions change.",
            ],
        }

    def build_xgboost_model_card(
        self,
        *,
        model_version: str,
        dataset_fingerprint: str | None,
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        calibration = metrics.get("calibration_evidence") or {}
        fairness = metrics.get("fairness_audit") or {}
        explainability = metrics.get("explainability") or {}
        baselines = metrics.get("baseline_comparisons") or {}
        required = {
            "dataset_lineage": bool(dataset_fingerprint and metrics.get("reviewed_label_snapshot_id")),
            "performance": metrics.get("f1_score") is not None,
            "baselines": bool(baselines),
            "calibration": bool(calibration),
            "fairness": bool(fairness),
            "explainability": bool(explainability),
            "preprocessing": bool(metrics.get("preprocessing_evidence")),
            "limitations": bool(metrics.get("leakage_risks")),
        }
        return {
            "schema_version": "future_model_card_v2",
            "status": "complete" if all(required.values()) else "incomplete",
            "completion_checks": required,
            "dataset_fingerprint": dataset_fingerprint,
            "model_identity": {
                "model_type": "xgboost",
                "model_version": model_version,
                "lifecycle_state": "candidate",
            },
            "intended_use": "Prioritise curriculum-labour alignment cases for authorised human review.",
            "intended_users": ["curriculum experts", "institutional analysts", "authorised decision committees"],
            "out_of_scope_uses": [
                "automatic curriculum approval or rejection",
                "student admission, progression, or employment decisions",
                "claims of demographic fairness without valid protected-attribute evidence",
            ],
            "decision_authority": "Advisory only; human curriculum governance retains final authority.",
"dataset": {
                "snapshot_id": metrics.get("reviewed_label_snapshot_id"),
                "snapshot_version": metrics.get("reviewed_label_snapshot_version"),
                "fingerprint": dataset_fingerprint,
                "training_contract": metrics.get("training_data_contract"),
            },
            "label_provenance": metrics.get("label_provenance") or "independent_expert_validation",
            "experimental_uat": bool(metrics.get("experimental_uat")),
            "target_definition": metrics.get("target_definition"),
            "validation_design": {
                "ordering_policy": metrics.get("training_ordering_policy"),
                "cross_validation": metrics.get("timeseries_cv_folds"),
                "preprocessing": metrics.get("preprocessing_evidence"),
                "holdout_samples": metrics.get("test_samples"),
            },
            "performance": {
                key: metrics.get(key)
                for key in (
                    "precision", "recall", "f1_score", "roc_auc", "pr_auc",
                    "balanced_accuracy", "brier_score", "cv_mean_f1", "cv_worst_f1",
                )
            },
            "baseline_evidence": baselines,
            "calibration_evidence": calibration,
            "fairness_evidence": fairness,
            "explainability_evidence": explainability,
            "limitations": list(metrics.get("leakage_risks") or [])
            + list(calibration.get("limitations") or [])
            + list(fairness.get("limitations") or []),
            "monitoring_requirements": [
                "monitor calibration, class balance, subgroup behaviour, and source drift",
                "re-evaluate against the same declared baselines after retraining",
                "retain expert review and record overrides or disagreements",
            ],
            "promotion_requirements": [
                "successful automated tests",
                "acceptable calibration",
                "candidate outperforms declared baselines",
                "acceptable fold stability",
                "fairness and explainability evidence reviewed",
                "explicit authorised approval",
            ],
            "human_review_required": True,
        }

    def _insufficient_calibration(self, sample_count: int, reason: str) -> Dict[str, Any]:
        return {
            "status": "insufficient_data",
            "method": "equal_width_reliability_bins",
            "sample_count": sample_count,
            "reason": reason,
            "acceptance_threshold": {
                "minimum_holdout_rows": self.MIN_CALIBRATION_ROWS,
                "maximum_expected_calibration_error": self.MAX_ACCEPTABLE_ECE,
                "both_classes_required": True,
            },
            "reliability_bins": [],
        }


model_evidence_service = ModelEvidenceService()

