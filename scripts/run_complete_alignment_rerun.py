#!/usr/bin/env python3
"""Rerun the frozen alignment candidate and retain complete evaluation evidence."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_env(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def model_params(y, xgb_defaults):
    params = dict(xgb_defaults)
    positives = int(y.sum())
    negatives = int(len(y) - positives)
    if positives and negatives:
        params["scale_pos_weight"] = negatives / positives
    return params


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--snapshot-json", type=Path, required=True)
    parser.add_argument("--snapshot-version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.env_file:
        load_env(args.env_file)
    backend = args.repo / "backend"
    sys.path.insert(0, str(backend))

    import joblib
    import numpy as np
    import xgboost as xgb
    from sklearn.metrics import (
        average_precision_score, balanced_accuracy_score, brier_score_loss,
        confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score,
    )
    from app.services.fold_safe_preprocessing_service import fold_safe_preprocessing_service
    from app.services.model_service import ModelService
    from app.services.reviewed_alignment_training_dataset_service import ReviewedAlignmentTrainingDatasetService

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    export = json.loads(args.snapshot_json.read_text(encoding="utf-8"))
    if export.get("snapshot_version") != args.snapshot_version or len(export.get("records", [])) != 993:
        raise RuntimeError("Snapshot identity or row count does not match the frozen evaluation")
    builder = ReviewedAlignmentTrainingDatasetService()
    records = []
    for source in export["records"]:
        payload = {
            "document_id": source.get("document_id"),
            "version_id": source.get("version_id"),
            "curriculum_evidence": source.get("curriculum_evidence"),
            "labour_market_evidence": source.get("labour_market_evidence"),
            "evidence_metadata": source.get("evidence_metadata"),
        }
        records.append({
            "row_index": int(source["row_index"]),
            "task_id": str(source["task_id"]),
            "document_id": str(source.get("document_id")),
            "version_id": str(source.get("version_id")),
            "group_id": str(source.get("version_id") or source["task_id"]),
            "features": builder.build_features(payload),
            "continuous_target": (float(source["final_alignment_label"]) - 1.0) / 4.0,
            "final_alignment_label": int(source["final_alignment_label"]),
            "chronology": builder._chronology(payload, int(source["row_index"])),
        })
    records.sort(key=lambda item: (item["chronology"]["sort_key"], item["row_index"]))
    dataset = {"records": records, "snapshot_version": export["snapshot_version"], "dataset_fingerprint": export["dataset_fingerprint"]}
    service = ModelService()

    records = dataset["records"]
    raw_names = sorted(set().union(*(row["features"].keys() for row in records)))
    raw_matrix = np.asarray([[float(row["features"].get(name, 0.0) or 0.0) for name in raw_names] for row in records])
    continuous = np.asarray([row["continuous_target"] for row in records], dtype=float)
    target_threshold = 0.35
    target = (continuous >= target_threshold).astype(int)
    groups = [str(row["group_id"]) for row in records]
    split_idx = service._group_safe_boundary(groups, int(len(records) * 0.8), 4, len(records) - 2) or int(len(records) * 0.8)
    desired_train_end = max(2, split_idx - max(1, int(split_idx * 0.15)))
    train_end = service._group_safe_boundary(groups[:split_idx], desired_train_end, 2, split_idx - 1) or desired_train_end
    validation_pre = fold_safe_preprocessing_service.fit(raw_matrix[:train_end], raw_names)
    x_train = fold_safe_preprocessing_service.transform(raw_matrix[:train_end], validation_pre)
    x_validation = fold_safe_preprocessing_service.transform(raw_matrix[train_end:split_idx], validation_pre)
    defaults = {
        "max_depth": 4, "learning_rate": 0.05, "n_estimators": 200,
        "objective": "binary:logistic", "eval_metric": "logloss",
        "random_state": 42, "scale_pos_weight": 1.0, "subsample": 0.8,
        "colsample_bytree": 0.8, "reg_alpha": 0.1, "reg_lambda": 1.0,
        "min_child_weight": 3,
    }
    validation_model = xgb.XGBClassifier(**model_params(target[:train_end], defaults))
    validation_model.fit(x_train, target[:train_end], verbose=False)
    validation_prob = validation_model.predict_proba(x_validation)[:, 1]
    candidates = []
    for threshold in np.arange(0.25, 0.76, 0.05):
        prediction = (validation_prob >= round(float(threshold), 2)).astype(int)
        candidates.append((float(f1_score(target[train_end:split_idx], prediction, zero_division=0)), float(balanced_accuracy_score(target[train_end:split_idx], prediction)), float(recall_score(target[train_end:split_idx], prediction, zero_division=0)), round(float(threshold), 2)))
    operating_threshold = max(candidates) [3]

    preprocessor = fold_safe_preprocessing_service.fit(raw_matrix[:split_idx], raw_names)
    train_matrix = fold_safe_preprocessing_service.transform(raw_matrix[:split_idx], preprocessor)
    holdout_matrix = fold_safe_preprocessing_service.transform(raw_matrix[split_idx:], preprocessor)
    candidate = xgb.XGBClassifier(**model_params(target[:split_idx], defaults))
    candidate.fit(train_matrix, target[:split_idx], verbose=False)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifact_target = out / f"xgboost_reproducibility_rerun_{stamp}.pkl"
    joblib.dump(candidate, artifact_target)
    holdout_prob = candidate.predict_proba(holdout_matrix)[:, 1]
    holdout_pred = (holdout_prob >= operating_threshold).astype(int)

    holdout_path = out / "holdout_predictions.csv"
    with holdout_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["row_index", "task_id", "version_id", "split", "continuous_target", "binary_target", "predicted_probability", "operating_threshold", "predicted_class", "correct"])
        for local, row_index in enumerate(range(split_idx, len(records))):
            row = records[row_index]
            writer.writerow([row["row_index"], row["task_id"], row["version_id"], "holdout", f"{continuous[row_index]:.8f}", int(target[row_index]), f"{holdout_prob[local]:.12f}", f"{operating_threshold:.8f}", int(holdout_pred[local]), int(holdout_pred[local] == target[row_index])])

    split_path = out / "split_membership.csv"
    with split_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["row_index", "task_id", "version_id", "split"])
        for index, row in enumerate(records):
            split = "train" if index < train_end else "validation" if index < split_idx else "holdout"
            writer.writerow([row["row_index"], row["task_id"], row["version_id"], split])

    folds = service._chronological_group_folds(groups, min(5, max(2, len(raw_matrix) // 12)))
    fold_path = out / "fold_predictions.csv"
    with fold_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["fold", "row_index", "task_id", "version_id", "continuous_target", "binary_target", "predicted_probability", "operating_threshold", "predicted_class", "correct"])
        for fold_number, (train_idx, val_idx) in enumerate(folds, start=1):
            y_train, y_val = target[train_idx], target[val_idx]
            if len(np.unique(y_train)) < 2 or len(np.unique(y_val)) < 2:
                continue
            fold_pre = fold_safe_preprocessing_service.fit(raw_matrix[train_idx], raw_names)
            x_train = fold_safe_preprocessing_service.transform(raw_matrix[train_idx], fold_pre)
            x_val = fold_safe_preprocessing_service.transform(raw_matrix[val_idx], fold_pre)
            model = xgb.XGBClassifier(**model_params(y_train, defaults))
            model.fit(x_train, y_train, verbose=False)
            probabilities = model.predict_proba(x_val)[:, 1]
            predictions = (probabilities >= 0.5).astype(int)
            for local, index in enumerate(val_idx):
                row = records[int(index)]
                writer.writerow([fold_number, row["row_index"], row["task_id"], row["version_id"], f"{continuous[index]:.8f}", int(target[index]), f"{probabilities[local]:.12f}", "0.50000000", int(predictions[local]), int(predictions[local] == target[index])])

    tn, fp, fn, tp = [int(value) for value in confusion_matrix(target[split_idx:], holdout_pred, labels=[0, 1]).ravel()]
    reproduced = {
        "run_type": "controlled_reproducibility_rerun_with_evidence_retention",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_version": dataset["snapshot_version"],
        "dataset_fingerprint": dataset["dataset_fingerprint"],
        "training_matrix_fingerprint": None,
        "rows": len(records),
        "split_counts": {"train": train_end, "validation": split_idx - train_end, "holdout": len(records) - split_idx},
        "target_threshold": target_threshold,
        "operating_threshold": operating_threshold,
        "metrics": {
            "precision": float(precision_score(target[split_idx:], holdout_pred, zero_division=0)),
            "recall": float(recall_score(target[split_idx:], holdout_pred, zero_division=0)),
            "f1": float(f1_score(target[split_idx:], holdout_pred, zero_division=0)),
            "roc_auc": float(roc_auc_score(target[split_idx:], holdout_prob)),
            "pr_auc": float(average_precision_score(target[split_idx:], holdout_prob)),
            "balanced_accuracy": float(balanced_accuracy_score(target[split_idx:], holdout_pred)),
            "brier_score": float(brier_score_loss(target[split_idx:], holdout_prob)),
            "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        },
        "selection_policy": "frozen target threshold from the original run; operating threshold reselected on the same chronological validation partition",
        "artifact": {"filename": artifact_target.name, "sha256": sha256(artifact_target), "bytes": artifact_target.stat().st_size},
        "software_versions": {name: importlib.metadata.version(name) for name in ("python-dateutil", "numpy", "pandas", "scikit-learn", "xgboost", "joblib", "sqlalchemy")},
        "python_version": sys.version,
        "source_commit": os.popen(f'git -C "{args.repo}" rev-parse HEAD').read().strip(),
    }
    dump(out / "rerun_evidence.json", reproduced)
    hashes = []
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            hashes.append(f"{sha256(path)}  {path.name}")
    (out / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "artifact": artifact_target.name, "artifact_sha256": sha256(artifact_target), "metrics": reproduced["metrics"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
