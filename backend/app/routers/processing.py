"""
Processing phase endpoints.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.services.audit_service import log_audit_event
from app.services.processing_orchestrator_service import processing_orchestrator_service
from app.services.operational_job_service import operational_job_service
from app.services.validated_regeneration_service import validated_regeneration_service


router = APIRouter(
    prefix="/processing",
    tags=["processing"],
)


@router.get("/summary")
def processing_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return processing_orchestrator_service.summary(db)


@router.get("/validated-regeneration/readiness")
def validated_regeneration_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
):
    return {
        **validated_regeneration_service.readiness(db),
        "latest_manifest": validated_regeneration_service.latest_manifest(db),
    }


@router.post(
    "/validated-regeneration/run",
    status_code=status.HTTP_202_ACCEPTED,
)
def run_validated_regeneration(
    horizon_periods: int = Query(default=4, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
):
    readiness = validated_regeneration_service.readiness(db)
    if readiness["status"] != "ready":
        from fastapi import HTTPException

        failed = [
            check["key"]
            for check in readiness["checks"]
            if check["status"] == "blocked"
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Validated evidence regeneration is blocked",
                "failed_checks": failed,
            },
        )
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="processing.validated_regeneration",
        requested_by=current_user.identity_id,
        parameters={"horizon_periods": horizon_periods},
    )
    log_processing_job_action(
        db,
        current_user,
        "run_validated_regeneration",
        job,
        created,
        {"horizon_periods": horizon_periods},
    )
    return {
        "accepted": created,
        "coalesced": not created,
        "job": operational_job_service.to_dict(job),
    }


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_processing_phase(
    limit: int = Query(default=10000, ge=1, le=100000),
    horizon_periods: int = Query(default=4, ge=1, le=24),
    run_analytics: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if run_analytics:
        return run_validated_regeneration(
            horizon_periods=horizon_periods,
            db=db,
            current_user=current_user,
        )
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="processing.readiness",
        requested_by=current_user.identity_id,
        parameters={
            "limit": limit,
            "horizon_periods": horizon_periods,
            "run_analytics": run_analytics,
        },
    )
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="processing_phase",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="processing.api",
        action="run_processing_phase",
        result="accepted" if created else "coalesced",
        metadata={
            "operational_job_id": str(job.job_id),
            "limit": limit,
            "horizon_periods": horizon_periods,
            "run_analytics": run_analytics,
        },
    )
    db.commit()
    return {
        "accepted": created,
        "coalesced": not created,
        "job": operational_job_service.to_dict(job),
    }


@router.post("/run/full", status_code=status.HTTP_202_ACCEPTED)
def run_full_processing_pipeline(
    limit: int = Query(default=10000, ge=1, le=100000),
    horizon_periods: int = Query(default=4, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    return run_validated_regeneration(
        horizon_periods=horizon_periods,
        db=db,
        current_user=current_user,
    )


@router.post("/run/alignment", status_code=status.HTTP_202_ACCEPTED)
def rerun_alignment_processing(
    version_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    return run_validated_regeneration(
        horizon_periods=4,
        db=db,
        current_user=current_user,
    )


@router.post("/run/forecasts", status_code=status.HTTP_202_ACCEPTED)
def rerun_forecast_processing(
    horizon_periods: int = Query(default=4, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    return run_validated_regeneration(
        horizon_periods=horizon_periods,
        db=db,
        current_user=current_user,
    )


@router.post("/run/recommendations", status_code=status.HTTP_202_ACCEPTED)
def rerun_recommendation_processing(
    version_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    return run_validated_regeneration(
        horizon_periods=4,
        db=db,
        current_user=current_user,
    )


def log_processing_job_action(
    db: Session,
    current_user: User,
    action: str,
    job,
    created: bool,
    metadata: dict,
) -> None:
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="operational_job",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="processing.api",
        action=action,
        result="accepted" if created else "coalesced",
        metadata={
            "operational_job_id": str(job.job_id),
            "job_type": job.job_type,
            **metadata,
        },
    )
    db.commit()


def log_processing_action(db: Session, current_user: User, action: str, result: dict, metadata: dict) -> None:
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="processing_phase",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="processing.api",
        action=action,
        result=(result.get("readiness") or {}).get("status", "generated"),
        metadata={
            "report_id": result.get("report_id"),
            "report_type": result.get("report_type"),
            "stage_key": result.get("stage_key"),
            **metadata,
        },
    )
    db.commit()
