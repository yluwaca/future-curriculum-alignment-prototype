"""
Fairness router for FUTURE Platform.

Endpoints:
- POST /fairness/audit — run demographic parity check on recent predictions
- GET /fairness/status — get latest fairness audit result
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
)
from app.core.permissions import (
    require_permission,
)
from app.db.session import get_db
from app.models.predictive_output import PredictiveOutput
from app.services.fairness_audit_service import FairnessAuditService

router = APIRouter(
    prefix="/fairness",
    tags=["fairness"],
)


@router.post("/audit")
def run_fairness_audit(
    threshold: float = Query(0.1, ge=0.01, le=1.0),
    _user=Depends(require_permission("system.admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Run demographic parity fairness audit on recent alignment predictions.

    Paper requirement: demographic parity <= 0.1
    Uses campus/faculty as geographic proxy (no POPIA-protected attributes).
    """
    recent = (
        db.query(PredictiveOutput)
        .order_by(PredictiveOutput.prediction_timestamp.desc())
        .limit(500)
        .all()
    )

    if not recent:
        return {"status": "no_data", "message": "No predictions to audit"}

    alignment_scores = [
        {
            "faculty": pred.faculty or "unknown",
            "alignment_score": float(pred.alignment_score or 0),
        }
        for pred in recent
    ]

    svc = FairnessAuditService(db)
    result = svc.audit_alignment_predictions(
        alignment_scores, threshold=threshold
    )

    result["sample_size"] = len(recent)
    result["threshold"] = threshold

    return result


@router.get("/status")
def fairness_status(
    _user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get latest fairness audit status from model metrics."""
    from app.services.model_service import ModelService

    svc = ModelService()
    metrics = svc.xgboost_metrics

    fairness = metrics.get("fairness_audit", None)
    blocked = metrics.get("fairness_blocked", None)

    return {
        "fairness_audit": fairness,
        "model_blocked": blocked,
        "model_version": svc.model_version,
    }
