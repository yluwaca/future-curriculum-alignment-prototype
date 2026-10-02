#!/usr/bin/env python
"""Run the reproducible UAT evaluation pipeline over the locked reviewed dataset.

Pipeline (all logic delegated to backend/app services - no duplicated modelling):
  1. Load the locked reviewed alignment-label snapshot and verify its integrity.
  2. Train the XGBoost alignment candidate with chronological TimeSeriesSplit CV
     (no shuffling) and report holdout F1 / ROC-AUC / Precision / Recall.
  3. Train the LSTM forecast candidate with expanding-window walk-forward
     backtesting and report holdout RMSE / MAE / sMAPE.
  4. Compute descriptive TF-IDF Gap Scores, gap = 1 - cos(c, d), for the locked
     evidence pairs (baseline vs simulated post-recommendation curriculum).
  5. Write a Markdown + JSON evidence report.

Outputs are written to docs/uat_evaluation/ by default.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _load_backend_env() -> None:
    """Load backend/.env first so Settings() works from any working directory."""
    env_path = BACKEND / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_backend_env()

import numpy as np  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.label_dataset_snapshot import LabelDatasetSnapshotRow  # noqa: E402
from app.services.feature_engineering import FeatureEngineer  # noqa: E402
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service  # noqa: E402
from app.services.model_service import ModelService  # noqa: E402
from app.services.reviewed_alignment_training_dataset_service import (  # noqa: E402
    ReviewedAlignmentTrainingDatasetService,
    reviewed_alignment_training_dataset_service,
)


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


# =====================================================
# Step 1 - Locked dataset
# =====================================================

def load_locked_dataset(db: Session, snapshot_version: str | None) -> Dict[str, Any]:
    if snapshot_version:
        from app.models.label_dataset_snapshot import LabelDatasetSnapshot

        snapshot = (
            db.query(LabelDatasetSnapshot)
            .filter(
                LabelDatasetSnapshot.snapshot_version == snapshot_version,
                LabelDatasetSnapshot.lifecycle_state == "approved_locked",
            )
            .first()
        )
        if snapshot is None:
            raise RuntimeError(f"Approved locked snapshot {snapshot_version!r} was not found")
    else:
        snapshot = label_dataset_snapshot_service.latest_locked(db)
    if snapshot is None:
        raise RuntimeError(
            "No approved_locked reviewed-label snapshot found; "
            "lock a dataset before running the UAT evaluation."
        )

    manifest = dict(snapshot.manifest or {})
    notes = str(snapshot.notes or "")
    if manifest.get("synthetic") or "SYNTHETIC" in notes.upper() or "synthetic" in str(
        (manifest.get("dataset_card") or {})
    ):
        raise RuntimeError(
            f"Refusing to evaluate {snapshot.snapshot_version}: it is flagged SYNTHETIC/DEV-ONLY "
            "and must never be reported as an empirical research result. Lock a dataset of "
            "independently reviewed expert labels first, or pass its version explicitly."
        )

    dataset = reviewed_alignment_training_dataset_service.load(db, snapshot)
    print(
        f"[1/4] Locked dataset verified: {dataset['snapshot_version']} "
        f"rows={dataset['row_count']} dated={dataset['dated_row_count']}"
    )
    return dataset


# =====================================================
# Steps 2 & 3 - Model candidates via existing services
# =====================================================

def run_xgboost_evaluation(db: Session, snapshot_id: Any) -> Dict[str, Any]:
    service = ModelService()
    metrics = service.train_xgboost_alignment_model(db=db, label_snapshot_id=snapshot_id)
    folds = [f for f in metrics.get("timeseries_cv_folds", []) if f.get("status") == "evaluated"]
    summary = {
        "holdout": {
            "f1": metrics.get("f1_score"),
            "roc_auc": metrics.get("roc_auc"),
            "precision": metrics.get("precision"),
            "recall": metrics.get("recall"),
            "pr_auc": metrics.get("pr_auc"),
            "balanced_accuracy": metrics.get("balanced_accuracy"),
            "brier_score": metrics.get("brier_score"),
            "operating_threshold": metrics.get("operating_threshold"),
        },
        "chronological_timeseries_cv": {
            "splits": len(folds),
            "shuffle": False,
            "cv_mean_f1": metrics.get("cv_mean_f1"),
            "cv_std_f1": metrics.get("cv_std_f1"),
            "cv_worst_f1": metrics.get("cv_worst_f1"),
            "cv_mean_roc_auc": metrics.get("cv_mean_roc_auc"),
        },
        "samples": {
            "training": metrics.get("training_samples"),
            "validation": metrics.get("validation_samples"),
            "test_holdout": metrics.get("test_samples"),
        },
        "selected_target_threshold": metrics.get("threshold"),
        "ordering_policy": metrics.get("training_ordering_policy"),
        "dataset_fingerprint": metrics.get("dataset_fingerprint"),
        "candidate_artifact": metrics.get("candidate_artifact"),
    }
    print(
        "[2/4] XGBoost holdout: "
        f"F1={_fmt(summary['holdout']['f1'])} AUC={_fmt(summary['holdout']['roc_auc'])} "
        f"P={_fmt(summary['holdout']['precision'])} R={_fmt(summary['holdout']['recall'])}"
    )
    return summary


def run_lstm_evaluation(db: Session) -> Dict[str, Any]:
    service = ModelService()
    metrics = service.train_lstm_forecast_model(db=db)
    folds = metrics.get("walk_forward_backtest_folds", [])
    summary = {
        "holdout": {
            "rmse": metrics.get("rmse"),
            "mae": metrics.get("mae"),
            "smape": metrics.get("smape"),
            "direction_accuracy": metrics.get("direction_accuracy"),
        },
        "walk_forward_backtesting": {
            "policy": "expanding_window_walk_forward_plus_holdout",
            "folds": len(folds),
            "mean_rmse": metrics.get("cv_mean_rmse"),
            "std_rmse": metrics.get("cv_std_rmse"),
            "worst_rmse": metrics.get("cv_worst_rmse"),
            "mean_mae": metrics.get("cv_mean_mae"),
            "mean_smape": metrics.get("cv_mean_smape"),
        },
        "baselines": {
            "best_baseline": metrics.get("best_baseline"),
            "baseline_rmse": metrics.get("baseline_rmse"),
            "rmse_improvement_pct": metrics.get("rmse_improvement_pct"),
        },
        "samples": {
            "training": metrics.get("training_samples"),
            "test_holdout": metrics.get("test_samples"),
        },
        "maturity_status": metrics.get("maturity_status"),
        "candidate_artifact": metrics.get("candidate_artifact"),
    }
    print(
        "[3/4] LSTM holdout: "
        f"RMSE={_fmt(summary['holdout']['rmse'])} MAE={_fmt(summary['holdout']['mae'])} "
        f"sMAPE={_fmt(summary['holdout']['smape'], 2)}% folds={summary['walk_forward_backtesting']['folds']}"
    )
    return summary


# =====================================================
# Step 4 - Descriptive TF-IDF Gap Score (1 - cos(c, d))
# =====================================================

def _pair_texts(row_payload: Dict[str, Any]) -> tuple[str, str]:
    to_text = ReviewedAlignmentTrainingDatasetService._text
    curriculum_text = to_text(row_payload.get("curriculum_evidence"))
    labour_items = row_payload.get("labour_market_evidence") or []
    labour_text = "\n".join(to_text(item) for item in labour_items) if isinstance(labour_items, list) else to_text(labour_items)
    return curriculum_text, labour_text


def compute_gap_scores(dataset: Dict[str, Any], top_k: int) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        rows = (
            db.query(LabelDatasetSnapshotRow)
            .filter(LabelDatasetSnapshotRow.snapshot_id == dataset["snapshot_id"])
            .order_by(LabelDatasetSnapshotRow.row_index.asc())
            .all()
        )
        pairs = [_pair_texts(dict(row.row_payload or {})) for row in rows]
    finally:
        db.close()

    engineer = FeatureEngineer()
    curriculum_texts = [c for c, _ in pairs]
    demand_texts = [d for _, d in pairs]
    engineer.fit_tfidf(curriculum_texts + demand_texts)

    c_vectors = engineer.transform_tfidf(curriculum_texts)
    d_vectors = engineer.transform_tfidf(demand_texts)
    vocabulary = engineer.feature_names

    baseline_gaps: List[float] = []
    simulated_gaps: List[float] = []
    for index in range(len(pairs)):
        baseline_gaps.append(
            FeatureEngineer.calculate_gap_score(c_vectors[index], d_vectors[index])
        )
        demand_weights = np.asarray(d_vectors[index]).reshape(-1)
        curriculum_weights = np.asarray(c_vectors[index]).reshape(-1)
        missing = [
            (vocabulary[idx], float(demand_weights[idx]))
            for idx in np.argsort(demand_weights)[::-1]
            if demand_weights[idx] > 0 and curriculum_weights[idx] == 0
        ][:top_k]
        remediated_text = curriculum_texts[index] + "\n" + " ".join(term for term, _ in missing)
        c_simulated = engineer.transform_tfidf([remediated_text])[0]
        simulated_gaps.append(
            FeatureEngineer.calculate_gap_score(c_simulated, d_vectors[index])
        )

    baseline_array = np.array(baseline_gaps, dtype=float)
    simulated_array = np.array(simulated_gaps, dtype=float)
    summary = {
        "definition": "gap = 1 - cos(tfidf(curriculum), tfidf(demand))",
        "tfidf_max_features": engineer.tfidf_max_features,
        "pairs_evaluated": len(pairs),
        "baseline": {
            "mean_gap_score": float(np.mean(baseline_array)),
            "median_gap_score": float(np.median(baseline_array)),
            "min_gap_score": float(np.min(baseline_array)),
            "max_gap_score": float(np.max(baseline_array)),
        },
        "simulated_post_recommendation": {
            "method": f"append top {top_k} absent demand terms per pair, recompute gap with same fitted vectorizer",
            "mean_gap_score": float(np.mean(simulated_array)),
            "median_gap_score": float(np.median(simulated_array)),
            "min_gap_score": float(np.min(simulated_array)),
            "max_gap_score": float(np.max(simulated_array)),
        },
        "improvement": {
            "mean_absolute_reduction": float(np.mean(baseline_array - simulated_array)),
            "mean_relative_reduction_pct": float(
                np.mean((baseline_array - simulated_array) / np.maximum(baseline_array, 1e-9)) * 100.0
            ),
        },
        "per_pair_baseline": [round(float(v), 6) for v in baseline_array],
        "per_pair_simulated": [round(float(v), 6) for v in simulated_array],
    }
    print(
        "[4/4] TF-IDF gap score: "
        f"baseline={_fmt(summary['baseline']['mean_gap_score'])} "
        f"post-recommendation={_fmt(summary['simulated_post_recommendation']['mean_gap_score'])}"
    )
    return summary


# =====================================================
# Step 5 - Reports
# =====================================================

def build_report(dataset: Dict[str, Any], xgboost: Dict[str, Any], lstm: Dict[str, Any], gaps: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "report_type": "uat_empirical_evaluation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "locked_dataset": {
            "snapshot_id": dataset["snapshot_id"],
            "snapshot_version": dataset["snapshot_version"],
            "dataset_fingerprint": dataset["dataset_fingerprint"],
            "row_count": dataset["row_count"],
            "dated_row_count": dataset["dated_row_count"],
            "undated_row_count": dataset["undated_row_count"],
            "ordering_policy": dataset["ordering_policy"],
            "integrity_verified": True,
        },
        "xgboost_alignment_classifier": xgboost,
        "lstm_forecast_model": lstm,
        "tfidf_gap_score": gaps,
        "reproducibility_notes": [
            "Chronological TimeSeriesSplit cross-validation without shuffling for XGBoost.",
            "Expanding-window walk-forward backtesting plus final holdout for LSTM.",
            "Fold-safe preprocessing: scalers/vectorizers fitted on training windows only.",
            "All metrics derive from the immutable approved_locked label snapshot.",
        ],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    ds = report["locked_dataset"]
    xgb_h = report["xgboost_alignment_classifier"]["holdout"]
    xgb_cv = report["xgboost_alignment_classifier"]["chronological_timeseries_cv"]
    xgb_s = report["xgboost_alignment_classifier"]["samples"]
    lstm_h = report["lstm_forecast_model"]["holdout"]
    lstm_wf = report["lstm_forecast_model"]["walk_forward_backtesting"]
    lstm_b = report["lstm_forecast_model"]["baselines"]
    gap = report["tfidf_gap_score"]

    lines: List[str] = []
    lines.append("# FUTURE Platform - UAT Empirical Evaluation Report")
    lines.append("")
    lines.append(f"Generated (UTC): {report['generated_at_utc']}")
    lines.append("")
    lines.append("## 1. Locked Reviewed Dataset")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Snapshot version | `{ds['snapshot_version']}` |")
    lines.append(f"| Snapshot ID | `{ds['snapshot_id']}` |")
    lines.append(f"| Dataset fingerprint | `{ds['dataset_fingerprint'][:16]}...` |")
    lines.append(f"| **Rows used** | **{ds['row_count']}** |")
    lines.append(f"| Dated rows | {ds['dated_row_count']} |")
    lines.append(f"| Ordering policy | {ds['ordering_policy']} |")
    lines.append(f"| Integrity verified | {ds['integrity_verified']} |")
    lines.append("")
    lines.append("## 2. XGBoost Alignment Classifier (holdout)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| F1 | {_fmt(xgb_h['f1'])} |")
    lines.append(f"| ROC-AUC | {_fmt(xgb_h['roc_auc'])} |")
    lines.append(f"| Precision | {_fmt(xgb_h['precision'])} |")
    lines.append(f"| Recall | {_fmt(xgb_h['recall'])} |")
    lines.append(f"| PR-AUC | {_fmt(xgb_h['pr_auc'])} |")
    lines.append(f"| Balanced accuracy | {_fmt(xgb_h['balanced_accuracy'])} |")
    lines.append(f"| Operating threshold | {_fmt(xgb_h['operating_threshold'], 2)} |")
    lines.append("")
    lines.append(f"Chronological TimeSeriesSplit CV (no shuffle): {xgb_cv['splits']} folds, "
                 f"mean F1 {_fmt(xgb_cv['cv_mean_f1'])}, worst F1 {_fmt(xgb_cv['cv_worst_f1'])}.")
    lines.append("")
    lines.append(f"Samples: train {xgb_s['training']}, validation {xgb_s['validation']}, "
                 f"holdout {xgb_s['test_holdout']}.")
    lines.append("")
    lines.append("## 3. LSTM Forecast Model (holdout)")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| RMSE | {_fmt(lstm_h['rmse'])} |")
    lines.append(f"| MAE | {_fmt(lstm_h['mae'])} |")
    lines.append(f"| sMAPE (%) | {_fmt(lstm_h['smape'], 2)} |")
    lines.append("")
    lines.append(f"Walk-forward backtesting ({lstm_wf['policy']}): {lstm_wf['folds']} folds, "
                 f"mean RMSE {_fmt(lstm_wf['mean_rmse'])}, worst RMSE {_fmt(lstm_wf['worst_rmse'])}, "
                 f"mean sMAPE {_fmt(lstm_wf['mean_smape'], 2)}%.")
    lines.append("")
    lines.append(f"Best transparent baseline: {lstm_b['best_baseline']} "
                 f"(RMSE {_fmt(lstm_b['baseline_rmse'])}); model improvement "
                 f"{_fmt(lstm_b['rmse_improvement_pct'], 2)}%.")
    lines.append("")
    lines.append("## 4. Descriptive TF-IDF Gap Score")
    lines.append("")
    lines.append(f"Definition: `{gap['definition']}` on {gap['pairs_evaluated']} locked evidence pairs.")
    lines.append("")
    lines.append("| Scenario | Mean | Median | Min | Max |")
    lines.append("| --- | --- | --- | --- | --- |")
    b = gap["baseline"]
    s = gap["simulated_post_recommendation"]
    lines.append(f"| Baseline | {_fmt(b['mean_gap_score'])} | {_fmt(b['median_gap_score'])} | "
                 f"{_fmt(b['min_gap_score'])} | {_fmt(b['max_gap_score'])} |")
    lines.append(f"| Simulated post-recommendation | {_fmt(s['mean_gap_score'])} | {_fmt(s['median_gap_score'])} | "
                 f"{_fmt(s['min_gap_score'])} | {_fmt(s['max_gap_score'])} |")
    lines.append("")
    lines.append(f"{s['method']}")
    lines.append("")
    imp = gap["improvement"]
    lines.append(f"Mean absolute reduction: {_fmt(imp['mean_absolute_reduction'])} "
                 f"(mean relative reduction {_fmt(imp['mean_relative_reduction_pct'], 2)}%).")
    lines.append("")
    lines.append("## 5. Reproducibility Notes")
    lines.append("")
    for note in report["reproducibility_notes"]:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(ROOT / "docs" / "uat_evaluation"))
    parser.add_argument("--snapshot-version", default=None,
                        help="Evaluate a specific approved_locked snapshot instead of the latest")
    parser.add_argument("--gap-top-k", type=int, default=10,
                        help="Absent demand terms appended per pair when simulating recommendations")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        dataset = load_locked_dataset(db, args.snapshot_version)
        xgboost_summary = run_xgboost_evaluation(db, dataset["snapshot_id"])
        lstm_summary = run_lstm_evaluation(db)
    finally:
        db.close()

    gap_summary = compute_gap_scores(dataset, top_k=args.gap_top_k)
    report = build_report(dataset, xgboost_summary, lstm_summary, gap_summary)
    report["runtime_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"uat_evaluation_{stamp}.json"
    md_path = output_dir / f"uat_evaluation_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print("\nEvaluation complete.")
    print(f"  JSON report: {json_path}")
    print(f"  Markdown   : {md_path}")


if __name__ == "__main__":
    main()
