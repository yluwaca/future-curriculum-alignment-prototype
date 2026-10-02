"""
Production service: security and operations readiness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.curriculum_document import CurriculumDocument
from app.models.data_source import DataSource
from app.models.generated_report import GeneratedReport
from app.models.ingestion_failure_event import IngestionFailureEvent
from app.models.ingestion_job import IngestionJob
from app.models.operational_job import OperationalJob
from app.models.system_alert import SystemAlert
from app.models.permission import Permission
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.tenant import Tenant
from app.models.user import User
from app.models.user_role import UserRole
from app.services.ingestion.credential_service import credential_service
from app.services.model_evaluation_service import payload_hash


class SecurityOperationsService:
    BACKUP_DIR = Path("backend/data/backups")

    def security_readiness_summary(self, db: Session) -> Dict[str, Any]:
        rbac = self.rbac_tenant_summary(db)
        credentials = self.credential_summary(db)
        scheduler = self.scheduler_summary(db)
        monitoring = self.monitoring_summary(db)
        backups = self.backup_summary(db)
        score = round(
            (
                rbac["quality_score"] * 0.25
                + credentials["quality_score"] * 0.20
                + scheduler["quality_score"] * 0.20
                + monitoring["quality_score"] * 0.20
                + backups["quality_score"] * 0.15
            ),
            4,
        )
        issues = (
            rbac["issues"]
            + credentials["issues"]
            + scheduler["issues"]
            + monitoring["issues"]
            + backups["issues"]
        )
        return {
            "phase": "Security & Operations Readiness",
            "score": score,
            "status": "ready" if score >= 0.75 and not issues else "needs_attention",
            "rbac_tenant_hardening": rbac,
            "credential_security": credentials,
            "scheduler": scheduler,
            "monitoring": monitoring,
            "backups": backups,
            "issues": issues[:12],
            "next_actions": [
                "Restrict mutating operations with explicit RBAC permission dependencies.",
                "Move from local encrypted database credentials to an external vault when deployed.",
                "Run due schedules from a background worker or platform scheduler.",
                "Export monitoring metrics to a production observability backend.",
                "Define retention/off-device replication and run an isolated full restore drill before production.",
            ],
        }

    def rbac_tenant_summary(self, db: Session) -> Dict[str, Any]:
        tenants = db.query(func.count(Tenant.tenant_id)).scalar() or 0
        active_tenants = db.query(func.count(Tenant.tenant_id)).filter(Tenant.status == "active").scalar() or 0
        roles = db.query(func.count(Role.role_id)).filter(Role.is_active.is_(True)).scalar() or 0
        permissions = db.query(func.count(Permission.permission_id)).filter(Permission.is_active.is_(True)).scalar() or 0
        role_permissions = db.query(func.count(RolePermission.role_id)).filter(RolePermission.is_active.is_(True)).scalar() or 0
        users = db.query(func.count(User.identity_id)).filter(User.is_active.is_(True)).scalar() or 0
        user_roles = db.query(func.count(UserRole.identity_id)).filter(UserRole.is_active.is_(True)).scalar() or 0
        tenant_sources = db.query(func.count(DataSource.source_id)).filter(DataSource.tenant_id.isnot(None)).scalar() or 0
        shared_sources = db.query(func.count(DataSource.source_id)).filter(DataSource.source_scope == "shared").scalar() or 0
        tenant_documents = db.query(func.count(CurriculumDocument.document_id)).filter(CurriculumDocument.tenant_id.isnot(None)).scalar() or 0
        issues = []
        if roles == 0 or permissions == 0:
            issues.append("RBAC roles/permissions are not fully populated.")
        if users and user_roles == 0:
            issues.append("Active users exist without active role assignments.")
        if tenants == 0:
            issues.append("No institution/tenant records are configured yet.")
        if tenant_sources == 0 and tenant_documents == 0:
            issues.append("Tenant-owned sources/documents are not yet operationally separated.")
        quality = round(
            min(
                1.0,
                (0.25 if roles else 0)
                + (0.20 if permissions else 0)
                + (0.20 if role_permissions else 0)
                + (0.15 if tenants else 0)
                + (0.20 if tenant_sources or tenant_documents else 0),
            ),
            4,
        )
        return {
            "quality_score": quality,
            "tenants": tenants,
            "active_tenants": active_tenants,
            "active_roles": roles,
            "active_permissions": permissions,
            "active_role_permissions": role_permissions,
            "active_users": users,
            "active_user_roles": user_roles,
            "tenant_sources": tenant_sources,
            "shared_sources": shared_sources,
            "tenant_curriculum_documents": tenant_documents,
            "issues": issues,
        }

    def credential_summary(self, db: Session) -> Dict[str, Any]:
        sources = db.query(DataSource).all()
        configured = [source for source in sources if source.auth_config]
        encrypted = 0
        signed_fallback = 0
        cleartext_secret_risks = 0
        fingerprints = []
        for source in configured:
            auth = source.auth_config or {}
            fmt = auth.get("_credential_format")
            if fmt == "fernet":
                encrypted += 1
            elif fmt == "signed_b64":
                signed_fallback += 1
            for key, value in auth.items():
                if key == "_credential_format":
                    continue
                if credential_service.is_secret_field(key) and isinstance(value, str) and not (
                    value.startswith("enc:") or value.startswith("sb64:")
                ):
                    cleartext_secret_risks += 1
            fingerprints.append(
                {
                    "source_id": str(source.source_id),
                    "source_key": source.source_key,
                    "credential_format": fmt or "unknown",
                    "fingerprint": credential_service.fingerprint(auth),
                    "masked": credential_service.mask_config(auth),
                }
            )
        issues = []
        if signed_fallback:
            issues.append("Some credentials use signed-base64 fallback; install cryptography/Fernet for stronger encryption.")
        if cleartext_secret_risks:
            issues.append("Potential cleartext secret fields were detected in source auth_config.")
        if configured and encrypted == 0:
            issues.append("No credentialed source is using Fernet encryption.")
        quality = round(
            min(1.0, (0.40 if configured else 0.25) + (encrypted / max(len(configured), 1) * 0.45) + (0.15 if cleartext_secret_risks == 0 else 0)),
            4,
        )
        return {
            "quality_score": quality,
            "credentialed_sources": len(configured),
            "fernet_encrypted_sources": encrypted,
            "signed_fallback_sources": signed_fallback,
            "cleartext_secret_risks": cleartext_secret_risks,
            "vault_status": "external_vault_pending",
            "local_encryption_available": bool(getattr(credential_service, "_fernet", None)),
            "fingerprints": fingerprints[:50],
            "issues": issues,
        }

    def scheduler_summary(self, db: Session) -> Dict[str, Any]:
        from app.services.operational_job_service import operational_job_service

        worker = operational_job_service.worker_status()
        sources = db.query(DataSource).filter(DataSource.status == "active").all()
        scheduled = []
        now = datetime.now(timezone.utc)
        for source in sources:
            schedule = (source.config or {}).get("schedule", {}) if isinstance(source.config, dict) else {}
            if not schedule:
                continue
            interval_hours = schedule.get("interval_hours") or schedule.get("every_hours")
            due = False
            due_at = None
            if interval_hours:
                anchor = source.last_success_at or source.updated_at or source.created_at
                due_at = anchor + self.hours_delta(float(interval_hours)) if anchor else now
                due = now >= due_at
            scheduled.append(
                {
                    "source_id": str(source.source_id),
                    "source_key": source.source_key,
                    "schedule": schedule,
                    "due": due,
                    "due_at": due_at.isoformat() if due_at else None,
                    "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
                }
            )
        queued = db.query(func.count(IngestionJob.job_id)).filter(IngestionJob.status == "queued").scalar() or 0
        operational_queued = db.query(func.count(OperationalJob.job_id)).filter(
            OperationalJob.status.in_(["queued", "retry_scheduled"])
        ).scalar() or 0
        operational_running = db.query(func.count(OperationalJob.job_id)).filter(
            OperationalJob.status == "running"
        ).scalar() or 0
        running = db.query(func.count(IngestionJob.job_id)).filter(IngestionJob.status == "running").scalar() or 0
        retry_scheduled = db.query(func.count(IngestionJob.job_id)).filter(IngestionJob.status == "retry_scheduled").scalar() or 0
        issues = []
        if not scheduled:
            issues.append("No active sources have schedules configured.")
        if queued > 100:
            issues.append("Large queued ingestion backlog detected.")
        due_count = sum(1 for item in scheduled if item["due"])
        quality = round(min(1.0, (0.35 if scheduled else 0.0) + (0.25 if due_count == 0 else 0.15) + (0.25 if retry_scheduled >= 0 else 0.0) + 0.15), 4)
        return {
            "quality_score": quality,
            "scheduled_sources": len(scheduled),
            "due_sources": due_count,
            "queued_jobs": queued,
            "operational_queued_jobs": operational_queued,
            "operational_running_jobs": operational_running,
            "running_jobs": running,
            "retry_scheduled_jobs": retry_scheduled,
            "scheduler_mode": "postgresql_durable_operational_worker",
            "background_worker_status": worker["status"],
            "background_worker_id": worker["worker_id"],
            "sample_schedules": scheduled[:50],
            "issues": issues,
        }

    def monitoring_summary(self, db: Session) -> Dict[str, Any]:
        jobs = db.query(func.count(IngestionJob.job_id)).scalar() or 0
        failed_jobs = db.query(func.count(IngestionJob.job_id)).filter(IngestionJob.status.in_(["failed", "completed_with_errors"])).scalar() or 0
        failure_events = db.query(func.count(IngestionFailureEvent.failure_id)).scalar() or 0
        audit_events = db.query(func.count(AuditEvent.event_id)).scalar() or 0
        degraded_sources = (
            db.query(func.count(DataSource.source_id))
            .filter((DataSource.consecutive_failures > 0) | (DataSource.circuit_state != "closed"))
            .scalar()
            or 0
        )
        active_alerts = db.query(func.count(SystemAlert.alert_id)).filter(
            SystemAlert.status.in_(["open", "acknowledged"])
        ).scalar() or 0
        critical_alerts = db.query(func.count(SystemAlert.alert_id)).filter(
            SystemAlert.status.in_(["open", "acknowledged"]),
            SystemAlert.severity == "critical",
        ).scalar() or 0
        delivered_alerts = db.query(func.count(SystemAlert.alert_id)).filter(
            SystemAlert.notification_status == "delivered"
        ).scalar() or 0
        webhook_configured = bool(os.getenv("FUTURE_ALERT_WEBHOOK_URL", "").strip())
        failure_rate = failed_jobs / max(jobs, 1)
        issues = []
        if degraded_sources:
            issues.append("Some data sources have failures or open/degraded circuits.")
        if failure_rate > 0.20:
            issues.append("Ingestion job failure rate is above 20%.")
        if audit_events == 0:
            issues.append("No audit events are available for operational traceability.")
        quality = round(min(1.0, 0.30 + (0.25 if audit_events else 0) + max(0.0, 0.25 - failure_rate) + (0.20 if degraded_sources == 0 else 0.05)), 4)
        return {
            "quality_score": quality,
            "ingestion_jobs": jobs,
            "failed_or_error_jobs": failed_jobs,
            "failure_rate": round(failure_rate, 4),
            "failure_events": failure_events,
            "audit_events": audit_events,
            "degraded_sources": degraded_sources,
            "active_alerts": active_alerts,
            "critical_alerts": critical_alerts,
            "delivered_alerts": delivered_alerts,
            "monitoring_mode": "health_readiness_prometheus_and_durable_alerts",
            "external_observability_status": "webhook_configured" if webhook_configured else "integration_ready",
            "webhook_configured": webhook_configured,
            "prometheus_endpoint": "/metrics",
            "issues": issues,
        }

    def backup_summary(self, db: Session) -> Dict[str, Any]:
        from app.services.backup_restore_service import backup_restore_service

        summary = backup_restore_service.latest_summary()
        latest = summary.get("latest")
        verification = (latest or {}).get("verification") or {}
        counts = self.backup_counts(db)
        issues = []
        if not latest:
            issues.append("No encrypted database/files/models backup has been created yet.")
        elif verification.get("status") != "passed":
            issues.append("The latest encrypted backup has not passed restore-readiness verification.")
        quality = 1.0 if latest and verification.get("status") == "passed" else (0.45 if latest else 0.10)
        return {
            "quality_score": quality,
            "backup_mode": summary["backup_mode"],
            "backup_directory": str(backup_restore_service.BACKUP_ROOT),
            "manifest_count": summary["backup_count"],
            "latest_manifest": summary["latest_manifest"],
            "snapshot_counts": counts,
            "database_dump_status": "verified" if verification.get("status") == "passed" else "pending",
            "encrypted_archive_status": "verified" if verification.get("status") == "passed" else "pending",
            "latest_backup_id": (latest or {}).get("backup_id"),
            "verification": verification or None,
            "issues": issues,
        }

    def generate_backup_manifest(self, db: Session, actor_id: Optional[str] = None) -> Dict[str, Any]:
        self.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_by": actor_id,
            "backup_mode": "manifest_only_local_readiness",
            "counts": self.backup_counts(db),
            "storage": {
                "backup_directory": str(self.BACKUP_DIR),
                "database_dump_status": "external_dump_pending",
                "encrypted_archive_status": "pending",
            },
        }
        digest = payload_hash(payload)
        filename = self.BACKUP_DIR / f"security_backup_manifest_{digest[:12]}.json"
        filename.write_text(self.json_dump(payload), encoding="utf-8")
        report = GeneratedReport(
            report_type="security_operations_backup_manifest",
            source_entity_type="operations",
            source_entity_id=None,
            generated_by=actor_id,
            status="generated",
            title="Security Operations Backup Manifest",
            summary={"backup_mode": payload["backup_mode"], "payload_hash": digest, **payload["counts"]},
            payload={**payload, "manifest_path": str(filename), "payload_hash": digest},
            payload_hash=digest,
            format_hint="json",
            notes="Manifest-only backup readiness record. Production should add encrypted DB/file snapshots.",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return {"report_id": str(report.report_id), "manifest_path": str(filename), "payload_hash": digest, "payload": report.payload}

    def backup_counts(self, db: Session) -> Dict[str, int]:
        return {
            "tenants": db.query(func.count(Tenant.tenant_id)).scalar() or 0,
            "data_sources": db.query(func.count(DataSource.source_id)).scalar() or 0,
            "raw_ingestion_records": db.query(func.count(RawIngestionRecord.record_id)).scalar() or 0,
            "ingestion_jobs": db.query(func.count(IngestionJob.job_id)).scalar() or 0,
            "generated_reports": db.query(func.count(GeneratedReport.report_id)).scalar() or 0,
            "audit_events": db.query(func.count(AuditEvent.event_id)).scalar() or 0,
        }

    @staticmethod
    def hours_delta(hours: float):
        from datetime import timedelta

        return timedelta(hours=hours)

    @staticmethod
    def json_dump(payload: Dict[str, Any]) -> str:
        import json

        return json.dumps(payload, indent=2, sort_keys=True, default=str)


security_operations_service = SecurityOperationsService()
