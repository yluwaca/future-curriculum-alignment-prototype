"""
Model registry service for managing model lifecycle states.

Implements the lifecycle: Draft -> Training -> Candidate -> Evaluated -> Rejected/Approved -> Active/Retired

Promotion must require:
- Reproducible dataset snapshot
- Successful automated tests
- No detected leakage
- Candidate outperforming the declared baseline
- Acceptable fold stability
- Recorded fairness assessment
- Explainability output
- Complete model card
- Explicit authorised approval
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.models.model_registry import (
    LIFECYCLE_STATES,
    VALID_TRANSITIONS,
    ModelRegistryEntry,
)
from app.services.model_evidence_service import model_evidence_service

logger = logging.getLogger(__name__)


class ModelRegistryService:
    """
    Service for managing model lifecycle states in the registry.
    """

    def __init__(self, db: Session):
        self.db = db

    def register_candidate(
        self,
        model_type: str,
        model_version: str,
        artifact_path: str,
        snapshot_id: Optional[str] = None,
        dataset_fingerprint: Optional[str] = None,
        metrics: Optional[Dict] = None,
        cv_folds: Optional[List] = None,
        notes: Optional[str] = None,
    ) -> ModelRegistryEntry:
        """
        Register a new trained model candidate. Training completion creates a
        candidate only; it never creates or replaces an active model.
        """
        metrics = metrics or {}
        artifact_size = None
        artifact_checksum = None
        if artifact_path and os.path.exists(artifact_path):
            artifact_size = os.path.getsize(artifact_path)
            digest = hashlib.sha256()
            with open(artifact_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            artifact_checksum = digest.hexdigest()

        model_card = self._build_model_card(
            model_type=model_type,
            model_version=model_version,
            metrics=metrics,
            dataset_fingerprint=dataset_fingerprint,
        )
        entry = ModelRegistryEntry(
            model_type=model_type,
            model_version=model_version,
            lifecycle_state="candidate",
            artifact_path=artifact_path,
            artifact_size_bytes=artifact_size,
            artifact_checksum=artifact_checksum,
            snapshot_id=snapshot_id,
            dataset_fingerprint=dataset_fingerprint,
            trained_at=datetime.now(timezone.utc),
            metrics=metrics,
            cv_folds=cv_folds or [],
            baseline_comparison=metrics.get("baseline_comparisons") or metrics.get("baselines") or {},
            fairness_assessment=metrics.get("fairness_audit") or {},
            explainability=metrics.get("explainability") or {},
            model_card=model_card,
            promotion_gates={
                "status": "not_checked",
                "message": "Candidate registered; gates must be checked before approval/promotion.",
            },
        )
        if notes:
            entry.notes = notes
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        logger.info(
            "Registered %s candidate %s (entry=%s)",
            model_type,
            model_version,
            entry.entry_id,
        )
        return entry

    @staticmethod
    def _build_model_card(
        model_type: str,
        model_version: str,
        metrics: Dict[str, Any],
        dataset_fingerprint: Optional[str],
    ) -> Dict[str, Any]:
        if model_type == "xgboost":
            return model_evidence_service.build_xgboost_model_card(
                model_version=model_version,
                dataset_fingerprint=dataset_fingerprint,
                metrics=metrics,
            )
        return {
            "model_type": model_type,
            "model_version": model_version,
            "intended_use": (
                "Candidate decision-support model for curriculum-labour market alignment/forecast review; not autonomous decision-making."
            ),
            "dataset_fingerprint": dataset_fingerprint,
            "training_phase": metrics.get("phase"),
            "metrics_summary": {
                key: metrics.get(key)
                for key in (
                    "precision", "recall", "f1_score", "roc_auc", "pr_auc",
                    "balanced_accuracy", "brier_score", "rmse", "mae", "smape", "mape",
                )
                if metrics.get(key) is not None
            },
            "limitations": metrics.get("readiness_warnings") or metrics.get("leakage_risks") or [],
            "human_review_required": True,
            "promotion_note": "Promotion requires explicit authorised approval after all gates pass.",
        }

    def get_entry(self, entry_id: UUID) -> Optional[ModelRegistryEntry]:
        """Get a registry entry by ID."""
        return (
            self.db.query(ModelRegistryEntry)
            .filter(ModelRegistryEntry.entry_id == entry_id)
            .first()
        )

    def get_active_model(self, model_type: str) -> Optional[ModelRegistryEntry]:
        """Get the current active model for a given type."""
        return (
            self.db.query(ModelRegistryEntry)
            .filter(
                and_(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.is_active == 1,
                    ModelRegistryEntry.lifecycle_state == "active",
                )
            )
            .first()
        )

    def get_latest_candidate(self, model_type: str) -> Optional[ModelRegistryEntry]:
        """Get the most recent candidate for a given type."""
        return (
            self.db.query(ModelRegistryEntry)
            .filter(
                and_(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.lifecycle_state.in_(
                        ["candidate", "evaluated", "approved"]
                    ),
                )
            )
            .order_by(desc(ModelRegistryEntry.trained_at))
            .first()
        )

    def list_entries(
        self,
        model_type: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[ModelRegistryEntry]:
        """List registry entries with optional filters."""
        query = self.db.query(ModelRegistryEntry)
        if model_type:
            query = query.filter(
                ModelRegistryEntry.model_type == model_type
            )
        if state:
            query = query.filter(
                ModelRegistryEntry.lifecycle_state == state
            )
        return (
            query.order_by(desc(ModelRegistryEntry.created_at))
            .limit(min(limit, 100))
            .all()
        )

    def update_state(
        self,
        entry_id: UUID,
        new_state: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        **kwargs,
    ) -> ModelRegistryEntry:
        """
        Transition a model to a new lifecycle state.
        Validates that the transition is allowed.
        """
        entry = self.get_entry(entry_id)
        if not entry:
            raise ValueError(f"Registry entry {entry_id} not found")

        current = entry.lifecycle_state
        allowed = VALID_TRANSITIONS.get(current, [])
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {current} -> {new_state}. "
                f"Allowed: {allowed}"
            )

        entry.lifecycle_state = new_state

        now = datetime.now(timezone.utc)
        if new_state == "evaluated":
            entry.evaluated_at = now
        elif new_state == "approved":
            pass
        elif new_state == "active":
            entry.promoted_at = now
            entry.promoted_by = actor_id
            entry.is_active = 1
            self._deactivate_previous(entry.model_type, entry.entry_id)
        elif new_state == "rejected":
            entry.rejected_by = actor_id
            entry.rejection_reason = reason
        elif new_state == "retired":
            entry.retired_at = now
            entry.is_active = 0
        elif new_state == "training":
            entry.trained_at = now

        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        self.db.commit()
        self.db.refresh(entry)
        logger.info(
            "Model %s %s: %s -> %s (actor=%s)",
            entry.model_type,
            entry.model_version,
            current,
            new_state,
            actor_id,
        )
        return entry

    def _deactivate_previous(
        self, model_type: str, exclude_entry_id: UUID
    ) -> None:
        """
        Deactivate the previously active model of the same type.
        Preserves it for rollback but marks is_active=0.
        """
        previous = (
            self.db.query(ModelRegistryEntry)
            .filter(
                and_(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.is_active == 1,
                    ModelRegistryEntry.entry_id != exclude_entry_id,
                )
            )
            .all()
        )
        for entry in previous:
            entry.is_active = 0
            entry.lifecycle_state = "retired"
            entry.retired_at = datetime.now(timezone.utc)
        if previous:
            self.db.commit()

    def rollback(
        self, model_type: str, actor_id: Optional[str] = None
    ) -> Optional[ModelRegistryEntry]:
        """
        Atomically rollback to the previously retired active model.
        The current active model is excluded from the rollback target so it
        cannot immediately reactivate itself.
        """
        current = self.get_active_model(model_type)
        current_id = current.entry_id if current else None

        previous_query = (
            self.db.query(ModelRegistryEntry)
            .filter(
                and_(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.lifecycle_state == "retired",
                )
            )
        )
        if current_id:
            previous_query = previous_query.filter(ModelRegistryEntry.entry_id != current_id)
        previous = previous_query.order_by(desc(ModelRegistryEntry.retired_at)).first()

        if not previous:
            return None

        try:
            now = datetime.now(timezone.utc)
            if current:
                current.is_active = 0
                current.lifecycle_state = "retired"
                current.retired_at = now
            previous.is_active = 1
            previous.lifecycle_state = "active"
            previous.promoted_at = now
            previous.promoted_by = actor_id
            self.db.commit()
            self.db.refresh(previous)
            logger.info(
                "Rolled back %s to %s (actor=%s)",
                model_type,
                previous.model_version,
                actor_id,
            )
            return previous
        except Exception:
            self.db.rollback()
            raise

    def get_rollback_candidate(
        self,
        model_type: str,
    ) -> Optional[ModelRegistryEntry]:
        """Return the next rollback target without changing registry state."""
        current = self.get_active_model(model_type)
        current_id = current.entry_id if current else None
        query = self.db.query(ModelRegistryEntry).filter(
            and_(
                ModelRegistryEntry.model_type == model_type,
                ModelRegistryEntry.lifecycle_state == "retired",
            )
        )
        if current_id:
            query = query.filter(ModelRegistryEntry.entry_id != current_id)
        return query.order_by(desc(ModelRegistryEntry.retired_at)).first()

    def check_promotion_gates(
        self, entry: ModelRegistryEntry
    ) -> Dict[str, Any]:
        """
        Check Phase 7 promotion gates for a candidate.
        """
        gates: Dict[str, Any] = {}
        metrics = entry.metrics or {}
        baselines = entry.baseline_comparison or metrics.get("baseline_comparisons") or metrics.get("baselines") or {}
        leakage_items = metrics.get("leakage_risks") or metrics.get("readiness_warnings") or []
        promotion_gate = metrics.get("promotion_gate") or {}

        gates["dataset_snapshot"] = {
            "passed": bool(entry.snapshot_id and entry.dataset_fingerprint),
            "message": "Dataset snapshot and fingerprint recorded" if entry.snapshot_id and entry.dataset_fingerprint else "Missing dataset snapshot or fingerprint",
        }
        gates["artifact_versioned"] = {
            "passed": bool(entry.artifact_path and entry.artifact_checksum and entry.artifact_size_bytes),
            "message": "Versioned artifact checksum and size recorded" if entry.artifact_checksum else "Artifact checksum/size not recorded",
        }
        tests = metrics.get("automated_tests") or {}
        gates["automated_tests"] = {
            "passed": tests.get("status") == "passed",
            "message": tests.get("summary") or "Automated test evidence not attached to candidate",
        }
        gates["no_detected_leakage"] = {
            "passed": not leakage_items and not str(promotion_gate.get("status", "")).startswith("blocked"),
            "message": "No leakage/readiness warnings recorded" if not leakage_items else "Warnings require review: " + " | ".join(map(str, leakage_items[:3])),
        }

        candidate_score = metrics.get("f1_score") if entry.model_type == "xgboost" else metrics.get("rmse")
        baseline_passed = False
        baseline_message = "No baseline comparison recorded"
        if baselines:
            if entry.model_type == "xgboost":
                baseline_scores = [
                    row.get("f1_score", row.get("f1"))
                    for row in baselines.values()
                    if isinstance(row, dict) and row.get("eligible_for_promotion_comparison", True)
                ]
                baseline_scores = [float(v) for v in baseline_scores if v is not None]
                baseline_passed = candidate_score is not None and baseline_scores and float(candidate_score) > max(baseline_scores)
                baseline_message = f"Candidate F1 {candidate_score}; best baseline F1 {max(baseline_scores) if baseline_scores else 'n/a'}"
            else:
                baseline_scores = [
                    row.get("rmse") for row in baselines.values() if isinstance(row, dict)
                ]
                baseline_scores = [float(v) for v in baseline_scores if v is not None]
                baseline_passed = candidate_score is not None and baseline_scores and float(candidate_score) < min(baseline_scores)
                baseline_message = f"Candidate RMSE {candidate_score}; best baseline RMSE {min(baseline_scores) if baseline_scores else 'n/a'}"
        gates["baseline_comparison"] = {"passed": bool(baseline_passed), "message": baseline_message}

        calibration = metrics.get("calibration_evidence") or {}
        gates["calibration"] = {
            "passed": entry.model_type != "xgboost" or calibration.get("status") == "passed",
            "message": (
                f"ECE {calibration.get('expected_calibration_error')}; "
                f"holdout n={calibration.get('sample_count')}"
                if calibration
                else "No untouched-holdout calibration evidence recorded"
            ),
        }

        folds = entry.cv_folds or []
        stability_passed = False
        if entry.model_type == "xgboost":
            stability_passed = metrics.get("cv_worst_f1") is not None and float(metrics.get("cv_worst_f1")) >= 0.5
            stability_message = f"Worst fold F1 {metrics.get('cv_worst_f1')}"
        else:
            mean_rmse = metrics.get("cv_mean_rmse")
            std_rmse = metrics.get("cv_std_rmse")
            stability_passed = mean_rmse is not None and std_rmse is not None and float(std_rmse) <= float(mean_rmse)
            stability_message = f"Mean RMSE {mean_rmse}, std RMSE {std_rmse}"
        gates["fold_stability"] = {
            "passed": bool(folds and stability_passed),
            "message": stability_message if folds else "No CV/backtest folds recorded",
        }

        fairness = entry.fairness_assessment or {}
        gates["fairness_assessment"] = {
            "passed": bool(fairness) and fairness.get("status") == "passed",
            "message": fairness.get("assessment_type") or fairness.get("status") or "No fairness/subgroup assessment recorded",
        }
        explainability = entry.explainability or {}
        explainability_outputs = (
            explainability.get("global_shap_summary")
            or explainability.get("shap_top_features")
        )
        gates["explainability"] = {
            "passed": bool(explainability)
            and bool(explainability.get("feature_labels_verified"))
            and bool(explainability_outputs),
            "message": "Explainability evidence recorded" if explainability else "No explainability output recorded",
        }
        gates["model_card"] = {
            "passed": bool(
                entry.model_card
                and entry.model_card.get("status") == "complete"
                and entry.model_card.get("intended_use")
            ),
            "message": (
                "Model card complete"
                if entry.model_card and entry.model_card.get("status") == "complete"
                else "Model card incomplete or not generated"
            ),
        }
        gates["explicit_authorised_approval"] = {
            "passed": entry.lifecycle_state in {"approved", "active"},
            "message": "Authorised approval recorded" if entry.lifecycle_state in {"approved", "active"} else "ADMIN approval not yet recorded",
        }
        entry.promotion_gates = gates
        self.db.flush()
        return gates

    def can_approve(self, entry: ModelRegistryEntry) -> tuple:
        gates = self.check_promotion_gates(entry)
        required = {k: v for k, v in gates.items() if k != "explicit_authorised_approval"}
        return all(g["passed"] for g in required.values()), gates

    def can_promote(self, entry: ModelRegistryEntry) -> tuple:
        gates = self.check_promotion_gates(entry)
        all_passed = all(g["passed"] for g in gates.values())
        return all_passed, gates

    def to_dict(self, entry: ModelRegistryEntry) -> Dict:
        """Serialize a registry entry to dict."""
        return {
            "entry_id": str(entry.entry_id),
            "model_type": entry.model_type,
            "model_version": entry.model_version,
            "lifecycle_state": entry.lifecycle_state,
            "artifact_path": entry.artifact_path,
            "artifact_size_bytes": entry.artifact_size_bytes,
            "snapshot_id": str(entry.snapshot_id) if entry.snapshot_id else None,
            "dataset_fingerprint": entry.dataset_fingerprint,
            "trained_at": entry.trained_at.isoformat() if entry.trained_at else None,
            "evaluated_at": entry.evaluated_at.isoformat() if entry.evaluated_at else None,
            "promoted_at": entry.promoted_at.isoformat() if entry.promoted_at else None,
            "retired_at": entry.retired_at.isoformat() if entry.retired_at else None,
            "metrics": entry.metrics,
            "cv_folds": entry.cv_folds,
            "baseline_comparison": entry.baseline_comparison,
            "fairness_assessment": entry.fairness_assessment,
            "explainability": entry.explainability,
            "promotion_gates": entry.promotion_gates,
            "model_card": entry.model_card,
            "promoted_by": entry.promoted_by,
            "rejected_by": entry.rejected_by,
            "rejection_reason": entry.rejection_reason,
            "is_active": entry.is_active == 1,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }


def get_model_registry_service(
    db: Session,
) -> ModelRegistryService:
    """Factory for ModelRegistryService."""
    return ModelRegistryService(db)
