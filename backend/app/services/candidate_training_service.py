"""Candidate-only model training orchestration used by durable jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.audit_service import AuditService
from app.services.model_dataset_snapshot_service import model_dataset_snapshot_service
from app.services.model_registry_service import get_model_registry_service
from app.services.model_service import ModelService
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service


class CandidateTrainingService:
    def __init__(self) -> None:
        self.model_service = ModelService()
        self.audit_service = AuditService()

    def readiness(self, db: Session) -> Dict[str, Any]:
        snapshot = label_dataset_snapshot_service.latest_locked(db)
        report: Dict[str, Any] = {
            "model_type": "xgboost",
            "ready": False,
            "blocked_reasons": [],
            "has_locked_label_snapshot": snapshot is not None,
        }
        if snapshot is None:
            report["blocked_reasons"].append(
                "No approved locked label dataset snapshot exists. "
                "Generate the technical-UAT review sample, complete first/second reviews, "
                "resolve disagreements, then lock the snapshot."
            )
            return report
        agreement = snapshot.agreement_statistics or {}
        dataset_mode = snapshot.dataset_mode or "technical_uat_researcher_operated"
        row_count = snapshot.row_count or 0
        kappa = agreement.get("cohens_kappa")
        report.update({
            "dataset_mode": dataset_mode,
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_version": snapshot.snapshot_version,
            "dataset_fingerprint": snapshot.dataset_fingerprint,
            "row_count": row_count,
            "minimum_rows_for_xgboost": 10,
            "cohens_kappa": kappa,
            "kappa_interpretation": agreement.get("kappa_interpretation"),
            "pairwise_agreement_rate": agreement.get("agreement_rate"),
            "experimental_uat": dataset_mode == "technical_uat_researcher_operated",
            "rule_assisted": dataset_mode == "rule_assisted_confirmed",
            "independent_expert_validation": dataset_mode == "independent_expert_validation",
        })
        if row_count < 10:
            report["blocked_reasons"].append(
                f"Locked snapshot has only {row_count} rows; XGBoost requires at least 10 eligible rows."
            )
        if not report["experimental_uat"] and not report["rule_assisted"] and not report["independent_expert_validation"]:
            report["blocked_reasons"].append("Unsupported label dataset mode in locked snapshot.")
        report["ready"] = not report["blocked_reasons"]
        if report["ready"]:
            report["note"] = (
                "Ready for experimental candidate-only training. Candidates trained on "
                "technical_uat_researcher_operated labels are experimental UAT artifacts and "
                "must NOT be promoted or represented as independently expert-validated models."
                if report["experimental_uat"]
                else "Ready for candidate-only training on independent expert labels."
            )
            if report["rule_assisted"]:
                report["note"] = (
                    "Ready for candidate-only technical training on portal-confirmed transparent rule-assisted labels. "
                    "Report separately from paired reviews; promotion remains blocked."
                )
        return report

    def train(self, db: Session, model_type: str, actor_id: str) -> Dict[str, Any]:
        if model_type not in {"xgboost", "lstm"}:
            raise ValueError(f"Unsupported model type: {model_type}")

        label_snapshot = None
        snapshot = None
        if model_type == "xgboost":
            label_snapshot = label_dataset_snapshot_service.latest_locked(db)
            if not label_snapshot:
                raise RuntimeError(
                    "XGBoost training requires an approved locked label dataset snapshot. "
                    + json.dumps(self.readiness(db), default=str)
                )

        if model_type == "xgboost":
            metrics = self.model_service.train_xgboost_alignment_model(
                db=db,
                label_snapshot_id=label_snapshot.snapshot_id,
            )
            metrics["dataset_mode"] = label_snapshot.dataset_mode
            metrics["experimental_uat"] = label_snapshot.dataset_mode == "technical_uat_researcher_operated"
            metrics["rule_assisted"] = label_snapshot.dataset_mode == "rule_assisted_confirmed"
            metrics["label_provenance"] = (
                "researcher_operated_uat_accounts_uq58x_untrusted"
                if metrics["experimental_uat"]
                else ("transparent_rule_assisted_portal_confirmation" if metrics["rule_assisted"] else "independent_expert_validation")
            )
            if metrics["experimental_uat"] or metrics["rule_assisted"]:
                existing_limitations = list(metrics.get("leakage_risks") or [])
                existing_limitations.append(
                    "Development candidate: trained on non-independent labels; "
                    "promotion must remain blocked and provenance reported."
                )
                metrics["leakage_risks"] = existing_limitations
        else:
            snapshot = model_dataset_snapshot_service.create_snapshot(
                db=db,
                model_type=model_type,
                actor_id=actor_id,
                model_config={
                    "algorithm": model_type,
                    "execution": "durable_operational_job",
                },
                notes=f"Snapshot captured immediately before {model_type.upper()} candidate training",
            )
            metrics = self.model_service.train_lstm_forecast_model(db=db)

        metrics["preparation_snapshot"] = (
            model_dataset_snapshot_service.to_dict(snapshot) if snapshot else None
        )
        metrics["dataset_snapshot"] = (
            label_dataset_snapshot_service.to_dict(label_snapshot)
            if label_snapshot
            else model_dataset_snapshot_service.to_dict(snapshot)
        )
        metrics["dataset_fingerprint"] = (
            label_snapshot.dataset_fingerprint if label_snapshot else snapshot.dataset_fingerprint
        )
        registry_service = get_model_registry_service(db)
        model_version = f"{model_type}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        entry = registry_service.register_candidate(
            model_type=model_type,
            model_version=model_version,
            artifact_path=metrics.get("model_path", ""),
            snapshot_id=str(label_snapshot.snapshot_id if label_snapshot else snapshot.snapshot_id),
            dataset_fingerprint=metrics["dataset_fingerprint"],
            metrics=metrics,
            cv_folds=metrics.get("timeseries_cv_folds", []),
            notes=(
                "Experimental UAT candidate trained on researcher-operated UAT labels; "
                "promotion blocked until independent expert validation."
                if (metrics.get("experimental_uat") and model_type == "xgboost")
                else "Registered automatically during durable candidate training"
            ),
        )
        entry.baseline_comparison = metrics.get("baseline_comparisons", {})
        if model_type == "xgboost":
            entry.fairness_assessment = metrics.get("fairness_audit", {})
            entry.explainability = metrics.get("explainability", {})
        db.commit()

        metrics["registry_entry_id"] = str(entry.entry_id)
        metrics["lifecycle_state"] = entry.lifecycle_state
        metrics["active_model_updated"] = False
        metrics["promotion_required"] = True
        self.audit_service.log_event(
            db=db,
            user_id=actor_id,
            action=f"TRAIN_{model_type.upper()}",
            resource="predictive_models",
            details=metrics,
        )
        return metrics


candidate_training_service = CandidateTrainingService()
