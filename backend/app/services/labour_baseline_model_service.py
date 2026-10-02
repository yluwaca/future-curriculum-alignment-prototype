"""Deterministic baseline model and classification metrics for the labour
workflow.

The baseline is intentionally readable and non-stochastic so that every run is
byte-for-byte reproducible:

* score = weight_confidence * confidence_feature
        + weight_overlap * token_overlap_feature
* prediction = 1 when score >= threshold, else 0
* confidence = the raw score, clipped to [0, 1]

It makes no claims of empirical validity; outputs are technical UAT evidence
used to sanity-check the dataset builder, split separation, and the evaluation
reporting pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.services.labour_training_dataset_service import (
    TrainingDatasetRecord,
    derive_label,
    derive_features,
)

BASELINE_MODEL_VERSION = "readable-baseline-v1"


def _counted(value: Optional[int]) -> int:
    return 0 if value is None else int(value)


def classification_metrics(
    predictions: Sequence[int],
    truths: Sequence[Optional[int]],
) -> Dict[str, Any]:
    """Compute a deterministic classification report (no external deps)."""
    pairs = [(int(p) if p is not None else 0, int(t)) for p, t in zip(predictions, truths) if t is not None]
    if not pairs:
        return {
            "rows_evaluated": 0,
            "tp": 0, "fp": 0, "tn": 0, "fn": 0,
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "accuracy": 0.0, "balanced_accuracy": 0.0,
            "positive_rate": 0.0, "negative_rate": 0.0,
        }

    tp = sum(1 for p, t in pairs if p == 1 and t == 1)
    tn = sum(1 for p, t in pairs if p == 0 and t == 0)
    fp = sum(1 for p, t in pairs if p == 1 and t == 0)
    fn = sum(1 for p, t in pairs if p == 0 and t == 1)

    precision = (tp / (tp + fp)) if (tp + fp) else 0.0
    recall = (tp / (tp + fn)) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(pairs) if pairs else 0.0
    sensitivity = recall
    specificity = (tn / (tn + fp)) if (tn + fp) else 0.0
    balanced_accuracy = (sensitivity + specificity) / 2.0

    return {
        "rows_evaluated": len(pairs),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
        "balanced_accuracy": round(balanced_accuracy, 6),
        "positive_rate": round(tp / len(pairs), 6),
        "negative_rate": round(fn / len(pairs), 6),
        "confusion_matrix": {"tn": _counted(tn), "fp": _counted(fp), "fn": _counted(fn), "tp": _counted(tp)},
    }


class BaselineModel:
    """Deterministic readable-baseline classifier for mapping-approval rows."""

    def __init__(
        self,
        weight_confidence: float = 0.55,
        weight_overlap: float = 0.45,
        threshold: float = 0.50,
    ) -> None:
        self.weight_confidence = float(weight_confidence)
        self.weight_overlap = float(weight_overlap)
        self.threshold = float(threshold)
        self.version = BASELINE_MODEL_VERSION

    def score(self, row: Mapping[str, Any]) -> float:
        features = derive_features(row)
        raw = (
            self.weight_confidence * _value(features.get("confidence"))
            + self.weight_overlap * _value(features.get("token_overlap"))
        )
        return max(0.0, min(1.0, raw))

    def predict(self, row: Mapping[str, Any]) -> int:
        return 1 if self.score(row) >= self.threshold else 0

    def predict_confidence(self, row: Mapping[str, Any]) -> float:
        return round(self.score(row), 6)

    def fit(self, rows: Sequence[Mapping[str, Any]] = ()) -> "BaselineModel":
        """No-op fit retained for API symmetry with learned models."""
        return self

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        rows: Sequence[Mapping[str, Any]],
        split: Optional[str] = None,
    ) -> Dict[str, Any]:
        evaluated = []
        for row in rows:
            if split is not None and row.get("split") != split:
                continue
            truth = derive_label(row)
            if truth is None:
                continue
            evaluated.append(
                {
                    "row_id": row["row_id"],
                    "prediction": self.predict(row),
                    "truth": truth,
                    "confidence": self.predict_confidence(row),
                }
            )
        predictions = [row["prediction"] for row in evaluated]
        truths = [row["truth"] for row in evaluated]
        report = classification_metrics(predictions, truths)
        report["model_version"] = self.version
        report["split"] = split if split is not None else "all"
        report["average_predicted_confidence"] = round(
            (sum(row["confidence"] for row in evaluated) / len(evaluated)) if evaluated else 0.0,
            6,
        )
        report["positive_predicted_rate"] = round(
            (sum(row["prediction"] for row in evaluated) / len(evaluated)) if evaluated else 0.0,
            6,
        )
        report["rows"] = evaluated
        return report

    def evaluate_split(self, record: TrainingDatasetRecord, split: str) -> Dict[str, Any]:
        return self.evaluate(record.rows, split=split)


def _value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def build_evaluation_report(
    model: BaselineModel,
    record: TrainingDatasetRecord,
    test_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the full model-evaluation report with required metadata."""
    test_report = test_report or model.evaluate_split(record, "test")
    return {
        "dataset_version": record.version,
        "dataset_schema_version": record.schema_version,
        "feature_list": record.feature_names,
        "target_definition": record.target_definition,
        "split_scheme": record.scheme,
        "seed": record.seed,
        "model_version": model.version,
        "model_parameters": {
            "weight_confidence": model.weight_confidence,
            "weight_overlap": model.weight_overlap,
            "threshold": model.threshold,
            "stochastic": False,
        },
        "metrics": {
            "precision": test_report.get("precision"),
            "recall": test_report.get("recall"),
            "f1": test_report.get("f1"),
            "accuracy": test_report.get("accuracy"),
            "balanced_accuracy": test_report.get("balanced_accuracy"),
            "average_predicted_confidence": test_report.get("average_predicted_confidence"),
            "positive_predicted_rate": test_report.get("positive_predicted_rate"),
        },
        "confusion_matrix": test_report.get("confusion_matrix"),
        "rows_evaluated": test_report.get("rows_evaluated"),
        "class_distribution": record.class_distribution,
        "missing_fields": record.missing,
        "masked_test_labels": record.masked_test_labels,
        "limitations": [
            "Synthetic fixtures only: validates technical behaviour, not empirical accuracy.",
            "Baseline is a deterministic threshold model; it is a control and not a production model.",
            "Real expert-labelled labour evidence and institutional validation are deferred.",
            "Test-split reviewer decisions are masked and excluded from training (no leakage).",
        ],
    }