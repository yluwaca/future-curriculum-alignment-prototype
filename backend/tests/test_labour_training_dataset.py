"""Tests for the deterministic labour-workflow training dataset and baseline.

These guard the technical contract of the dataset builder (deterministic
preprocessing, duplicate exclusion, train/val/test separation, missing values,
empty datasets, class-imbalance reporting, reproducible reruns, leakage
masking) and the evaluation report schema. Synthetic fixtures are technical
UAT evidence only.
"""

from __future__ import annotations

import pytest

from app.services.labour_baseline_model_service import (
    BaselineModel,
    build_evaluation_report,
    classification_metrics,
)
from app.services.labour_training_dataset_service import (
    FEATURE_NAMES,
    TrainingDatasetError,
    derive_features,
    derive_label,
    labour_training_dataset_service,
)


def fixtures(size=200, seed=7):
    return labour_training_dataset_service.synthetic_fixtures(size=size, seed=seed)


def test_deterministic_preprocessing():
    rows = fixtures(size=40, seed=3)
    first = [derive_features(row) for row in rows]
    second = [derive_features(row) for row in rows]
    assert first == second
    assert set(first[0]) == set(FEATURE_NAMES)
    for vector in first:
        for name, value in vector.items():
            assert name in FEATURE_NAMES
            assert 0.0 <= value <= 1.0, f"{name}={value}"


def test_duplicate_exclusion():
    rows = fixtures(size=60, seed=5)
    duplicated = [dict(row) for row in rows] + [dict(row) for row in rows[:10]]
    record = labour_training_dataset_service.build(duplicated, seed=1)
    assert record.deduplicated == 10
    assert record.to_manifest()["n_rows"] == len(rows)
    ids = [row["row_id"] for row in record.rows]
    assert len(ids) == len(set(ids))


def test_split_separation_no_posting_leakage():
    rows = fixtures(size=300, seed=11)
    record = labour_training_dataset_service.build(rows, seed=21)
    posting_to_splits = {}
    for row in record.rows:
        posting_to_splits.setdefault(row["posting_id"], set()).add(row["split"])
    for posting_id, splits in posting_to_splits.items():
        assert len(splits) == 1, f"posting {posting_id} leaked across {splits}"
    assert set(record.splits) == {"train", "validation", "test"}
    all_ids = (
        set(record.splits["train"]) | set(record.splits["validation"]) | set(record.splits["test"])
    )
    assert all_ids == {row["row_id"] for row in record.rows}


def test_missing_fields_reported():
    rows = fixtures(size=50, seed=9)
    for row in rows[:5]:
        row["mapping_status"] = None
    rows[0]["description"] = None
    rows[1]["confidence"] = None
    record = labour_training_dataset_service.build(rows, seed=4)
    assert record.missing["mapping_status"] >= 5
    assert record.missing["description"] >= 1
    assert record.missing["confidence"] >= 1
    for row in record.rows:
        vector = derive_features(row)
        assert "confidence" in vector and "posting_len" in vector


def test_empty_dataset_raises():
    with pytest.raises(TrainingDatasetError):
        labour_training_dataset_service.build([], seed=1)


def test_class_imbalance_report():
    rows = fixtures(size=500, seed=13)
    record = labour_training_dataset_service.build(rows, seed=6)
    overall = record.class_distribution["overall"]
    assert overall.get(0, 0) > 0 and overall.get(1, 0) > 0
    for split in ("train", "validation", "test"):
        assert split in record.class_distribution["per_split"]
    assert "unlabelled" not in overall


def test_reproducible_reruns():
    rows = fixtures(size=250, seed=17)
    first = labour_training_dataset_service.build(rows, seed=42)
    second = labour_training_dataset_service.build(rows, seed=42)
    assert first.version == second.version
    assert first.splits == second.splits
    assert first.to_manifest()["row_ids"] == second.to_manifest()["row_ids"]
    different_seed = labour_training_dataset_service.build(rows, seed=43)
    assert first.splits != different_seed.splits


def test_test_decision_masking_and_training_rows():
    rows = fixtures(size=120, seed=19)
    record = labour_training_dataset_service.build(rows, seed=8, mask_test_labels=True)
    assert record.masked_test_labels is True
    for row in record.split_rows("test"):
        assert derive_label(row) is None
        assert "_masked_label" in row
    training = labour_training_dataset_service.training_rows(record)
    assert training
    for row in training:
        assert row["split"] in ("train", "validation")
        assert derive_label(row) is not None


def test_time_scheme_groups_by_period():
    rows = fixtures(size=200, seed=23)
    service = labour_training_dataset_service
    time_record = service.build(rows, seed=31, mask_test_labels=False)
    assert time_record.scheme == "hash"
    time_service = labour_training_dataset_service.__class__(seed=31, scheme="time")
    record = time_service.build(rows, mask_test_labels=False)
    assert record.scheme == "time"
    posting_to_splits = {}
    for row in record.rows:
        posting_to_splits.setdefault(row["posting_id"], set()).add(row["split"])
    for splits in posting_to_splits.values():
        assert len(splits) == 1


def test_version_changes_when_rows_or_seed_change():
    rows = fixtures(size=80, seed=29)
    record_a = labour_training_dataset_service.build(rows, seed=100)
    record_b = labour_training_dataset_service.build(rows[:40], seed=100)
    assert record_a.version != record_b.version
    record_c = labour_training_dataset_service.build(rows, seed=101)
    assert record_a.version != record_c.version


def test_baseline_model_schema_and_determinism():
    rows = fixtures(size=400, seed=37)
    record = labour_training_dataset_service.build(rows, seed=12, mask_test_labels=False)
    model = BaselineModel()
    model.fit()
    test = model.evaluate_split(record, "test")
    report = build_evaluation_report(model, record, test_report=test)
    for key in (
        "dataset_version",
        "feature_list",
        "target_definition",
        "model_version",
        "metrics",
        "confusion_matrix",
        "rows_evaluated",
        "class_distribution",
        "limitations",
    ):
        assert key in report
    for key in ("precision", "recall", "f1", "accuracy", "balanced_accuracy"):
        assert key in report["metrics"]
    assert report["model_version"] == "readable-baseline-v1"
    assert report["confusion_matrix"] == test["confusion_matrix"]
    first = model.evaluate_split(record, "test")
    second = model.evaluate_split(record, "test")
    assert first["rows"] == second["rows"]


def test_classification_metrics_known_case():
    predictions = [1, 1, 0, 0, 1]
    truths = [1, 0, 0, 1, 1]
    report = classification_metrics(predictions, truths)
    assert report["tp"] == 2
    assert report["fp"] == 1
    assert report["tn"] == 1
    assert report["fn"] == 1
    assert report["precision"] == round(2 / 3, 6)
    assert report["recall"] == round(2 / 3, 6)
    assert report["f1"] == round(2 / 3, 6)
    assert report["rows_evaluated"] == 5


def test_classification_metrics_empty():
    report = classification_metrics([], [])
    assert report["rows_evaluated"] == 0
    assert report["precision"] == 0.0