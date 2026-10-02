"""
Security and operations readiness endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.services.audit_service import log_audit_event
from app.services.deployment_uat_service import deployment_uat_service
from app.services.security_operations_service import security_operations_service
from app.services.operational_job_service import operational_job_service
from app.services.backup_restore_service import backup_restore_service
from app.services.portal_uat_service import portal_uat_service
from app.services.monitoring_alert_service import monitoring_alert_service
from app.services.deployment_rollback_service import deployment_rollback_service
from app.services.research_claim_reconciliation_service import research_claim_reconciliation_service
from app.services.system_performance_service import system_performance_service


router = APIRouter(
    prefix="/operations",
    tags=["operations"],
)


@router.get("/security-readiness")
def security_operations_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return security_operations_service.security_readiness_summary(db)


@router.get("/deployment-readiness")
def deployment_uat_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return deployment_uat_service.deployment_readiness_summary()


@router.get("/rollback-readiness")
def rollback_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return deployment_rollback_service.readiness()


@router.post("/rollback/application-rehearsal", status_code=202)
def application_rollback_rehearsal(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="system.rollback.application_rehearsal",
        requested_by=current_user.identity_id,
        parameters={"live_switch": False, "verify_hashes": True},
        max_attempts=1,
    )
    return {"accepted": created, "coalesced": not created, "operational_job": operational_job_service.to_dict(job)}


@router.post("/rollback/database-rehearsal", status_code=202)
def database_rollback_rehearsal(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    readiness = deployment_rollback_service.readiness()
    if not readiness["database_rehearsal_ready"]:
        raise HTTPException(status_code=409, detail=readiness["database_authority"]["reason"])
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="system.rollback.database_rehearsal",
        requested_by=current_user.identity_id,
        parameters={"target": "generated_isolated_database", "live_database": False},
        max_attempts=1,
    )
    return {"accepted": created, "coalesced": not created, "operational_job": operational_job_service.to_dict(job)}


@router.get("/research-claims")
def research_claim_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return research_claim_reconciliation_service.reconcile(db, current_user.tenant_id)


@router.post("/research-claims/archive")
def archive_research_claim_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return research_claim_reconciliation_service.persist(
        db, current_user.tenant_id, current_user.identity_id
    )


@router.get("/portal-uat/latest")
def latest_portal_uat(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return portal_uat_service.latest(db) or {
        "result": "not_run",
        "summary": {"total": 0, "passed": 0, "expected_blocks": 0, "failed": 0},
        "golden_path": [],
        "failure_path": [],
    }


@router.post("/portal-uat/run")
def run_portal_uat(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return portal_uat_service.run(db, current_user.identity_id, current_user.identity_type)


@router.get("/monitoring")
def operations_monitoring_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return security_operations_service.monitoring_summary(db)


@router.get("/performance")
def system_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    """Return live, read-only performance measurements for this environment."""
    return system_performance_service.summary(db)


@router.post("/monitoring/evaluate")
def evaluate_operations_monitoring(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return monitoring_alert_service.evaluate(
        db, current_user.tenant_id, current_user.identity_id
    )


@router.get("/alerts")
def list_operations_alerts(
    alert_state: str = Query(default="active", alias="state"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    alerts = monitoring_alert_service.list_alerts(
        db, current_user.tenant_id, alert_state, limit
    )
    return {"alerts": [monitoring_alert_service.serialise(item) for item in alerts], "count": len(alerts)}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_operations_alert(
    alert_id: UUID,
    note: str = Body(min_length=3, max_length=2000, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    try:
        alert = monitoring_alert_service.acknowledge(
            db, current_user.tenant_id, alert_id, current_user.identity_id, note
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return monitoring_alert_service.serialise(alert)


@router.get("/scheduler")
def operations_scheduler_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return security_operations_service.scheduler_summary(db)


@router.get("/backups")
def operations_backup_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    summary = backup_restore_service.latest_summary()
    verification = summary.get("latest_verification") or {}
    latest = summary.get("latest_manifest")
    issues = []
    if not latest:
        issues.append("No backup manifest has been archived yet.")
    if verification.get("status") != "passed":
        issues.append("Latest backup verification is pending or not passed.")
    return {
        "quality_score": 1.0 if latest and verification.get("status") == "passed" else (0.45 if latest else 0.10),
        "issues": issues,
        **summary,
    }


@router.post("/backups/create", status_code=202)
def create_operations_backup(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="system.backup.create",
        requested_by=current_user.identity_id,
        parameters={"scope": "database_files_models", "encrypted": True},
        max_attempts=1,
    )
    return {
        "accepted": created,
        "coalesced": not created,
        "operational_job": operational_job_service.to_dict(job),
    }


@router.get("/backups/retention")
def backup_retention_plan(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    return backup_restore_service.retention_plan()


@router.get("/backups/restore-readiness")
def backup_restore_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    result = backup_restore_service.restore_drill_readiness()
    result.pop("administrative_database_url", None)
    return result


@router.post("/backups/retention/apply", status_code=202)
def apply_backup_retention(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="system.backup.retention",
        requested_by=current_user.identity_id,
        parameters={"mode": "quarantine", "destructive_delete": False},
        max_attempts=1,
    )
    return {"accepted": created, "coalesced": not created, "operational_job": operational_job_service.to_dict(job)}


@router.post("/backups/restore-drill", status_code=202)
def run_backup_restore_drill(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    readiness = backup_restore_service.restore_drill_readiness()
    if not readiness["ready"]:
        raise HTTPException(status_code=409, detail=readiness["reason"])
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="system.backup.restore_drill",
        requested_by=current_user.identity_id,
        parameters={"scope": "latest_backup", "target": "generated_isolated_database"},
        max_attempts=1,
    )
    return {"accepted": created, "coalesced": not created, "operational_job": operational_job_service.to_dict(job)}


@router.post("/backups/manifest")
def generate_operations_backup_manifest(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> Dict[str, Any]:
    result = security_operations_service.generate_backup_manifest(
        db=db,
        actor_id=current_user.identity_id,
    )
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="operations_backup",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="operations.api",
        action="generate_backup_manifest",
        result="success",
        metadata={"report_id": result.get("report_id"), "payload_hash": result.get("payload_hash")},
    )
    return result


@router.get("/jobs")
def list_operational_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    job_status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
) -> Dict[str, Any]:
    jobs = operational_job_service.list_jobs(db, limit=limit, status=job_status)
    return {
        "jobs": [operational_job_service.to_dict(job) for job in jobs],
        "count": len(jobs),
    }


@router.get("/jobs/{job_id}")
def get_operational_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
) -> Dict[str, Any]:
    job = operational_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Operational job not found")
    return operational_job_service.to_dict(job)


@router.post("/jobs/{job_id}/retry")
def retry_operational_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
) -> Dict[str, Any]:
    job = operational_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Operational job not found")
    try:
        retry_job = operational_job_service.retry(
            db, job, requested_by=current_user.identity_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return operational_job_service.to_dict(retry_job)


@router.post("/jobs/{job_id}/cancel")
def cancel_operational_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")
    ),
) -> Dict[str, Any]:
    job = operational_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Operational job not found")
    try:
        return operational_job_service.to_dict(
            operational_job_service.request_cancel(db, job)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


