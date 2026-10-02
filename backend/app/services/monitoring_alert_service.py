"""Operational monitoring rules, durable alerts, and optional webhook delivery."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import requests
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session

from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.operational_job import OperationalJob
from app.models.system_alert import SystemAlert
from app.services.backup_restore_service import backup_restore_service
from app.services.operational_job_service import operational_job_service


class MonitoringAlertService:
    ACTIVE = ("open", "acknowledged")

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def serialise(alert: SystemAlert) -> dict[str, Any]:
        return {
            "alert_id": str(alert.alert_id),
            "tenant_id": str(alert.tenant_id) if alert.tenant_id else None,
            "alert_key": alert.alert_key,
            "component": alert.component,
            "severity": alert.severity,
            "status": alert.status,
            "title": alert.title,
            "message": alert.message,
            "evidence": alert.evidence or {},
            "occurrence_count": alert.occurrence_count,
            "first_detected_at": alert.first_detected_at,
            "last_detected_at": alert.last_detected_at,
            "acknowledged_at": alert.acknowledged_at,
            "acknowledged_by": alert.acknowledged_by,
            "acknowledgement_note": alert.acknowledgement_note,
            "resolved_at": alert.resolved_at,
            "notification_status": alert.notification_status,
            "notification_attempts": alert.notification_attempts,
            "last_notification_at": alert.last_notification_at,
            "notification_error": alert.notification_error,
        }

    def evaluate(self, db: Session, tenant_id: UUID, actor_id: str | None = None) -> dict[str, Any]:
        now = self.now()
        since = now - timedelta(hours=24)
        rules: list[dict[str, Any]] = []

        db.execute(text("SELECT 1"))
        worker = operational_job_service.worker_status()
        if worker["status"] != "running":
            rules.append(self.rule("worker.stopped", "worker", "critical", "Background worker is stopped",
                                   "Durable ingestion, processing, model and backup jobs cannot execute.",
                                   {"worker_id": worker["worker_id"], "status": worker["status"]}))

        failed_ops = db.query(func.count(OperationalJob.job_id)).filter(
            OperationalJob.status == "failed", OperationalJob.completed_at >= since
        ).scalar() or 0
        if failed_ops:
            rules.append(self.rule("operational_jobs.failed_24h", "worker", "warning",
                                   "Operational jobs failed in the last 24 hours",
                                   f"{failed_ops} durable operational job(s) failed and require review.",
                                   {"failed_jobs_24h": failed_ops, "window_hours": 24}))

        tenant_filter = or_(IngestionJob.tenant_id == tenant_id, IngestionJob.tenant_id.is_(None))
        total_ingestion = db.query(func.count(IngestionJob.job_id)).filter(
            tenant_filter, IngestionJob.created_at >= since
        ).scalar() or 0
        failed_ingestion = db.query(func.count(IngestionJob.job_id)).filter(
            tenant_filter,
            IngestionJob.created_at >= since,
            IngestionJob.status.in_(["failed", "completed_with_errors"]),
        ).scalar() or 0
        rate = failed_ingestion / max(total_ingestion, 1)
        if total_ingestion >= 3 and rate > 0.20:
            rules.append(self.rule("ingestion.failure_rate", "ingestion", "warning",
                                   "Ingestion failure rate is above 20%",
                                   f"{failed_ingestion} of {total_ingestion} ingestion jobs failed or completed with errors.",
                                   {"failed": failed_ingestion, "total": total_ingestion, "rate": round(rate, 4)}))

        degraded = db.query(func.count(DataSource.source_id)).filter(
            or_(DataSource.tenant_id == tenant_id, DataSource.tenant_id.is_(None)),
            or_(DataSource.consecutive_failures > 0, DataSource.circuit_state != "closed"),
        ).scalar() or 0
        if degraded:
            rules.append(self.rule("sources.degraded", "sources", "warning", "Data sources are degraded",
                                   f"{degraded} accessible source(s) report failures or a non-closed circuit.",
                                   {"degraded_sources": degraded}))

        backup = backup_restore_service.latest_summary().get("latest") or {}
        verification = backup.get("verification") or {}
        if not backup:
            rules.append(self.rule("backup.missing", "backup", "critical", "No encrypted backup exists",
                                   "Create and verify an encrypted database/files/models backup.", {}))
        elif verification.get("status") != "passed":
            rules.append(self.rule("backup.unverified", "backup", "critical", "Latest backup is not verified",
                                   "The latest encrypted backup has not passed restore-readiness verification.",
                                   {"backup_id": backup.get("backup_id"), "verification": verification.get("status")}))

        active_keys = {item["alert_key"] for item in rules}
        touched: list[SystemAlert] = []
        for rule in rules:
            alert = db.query(SystemAlert).filter(
                SystemAlert.tenant_id == tenant_id,
                SystemAlert.alert_key == rule["alert_key"],
                SystemAlert.status.in_(self.ACTIVE),
            ).first()
            if alert:
                alert.last_detected_at = now
                alert.occurrence_count += 1
                alert.evidence = rule["evidence"]
                alert.message = rule["message"]
            else:
                alert = SystemAlert(
                    tenant_id=tenant_id, first_detected_at=now, last_detected_at=now, **rule
                )
                db.add(alert)
                db.flush()
                self.deliver(alert)
            touched.append(alert)

        stale = db.query(SystemAlert).filter(
            SystemAlert.tenant_id == tenant_id,
            SystemAlert.status.in_(self.ACTIVE),
        ).all()
        for alert in stale:
            if alert.alert_key not in active_keys:
                alert.status = "resolved"
                alert.resolved_at = now

        db.commit()
        return {
            "evaluated_at": now,
            "status": "attention_required" if rules else "healthy",
            "checks": {
                "database": "healthy",
                "worker": worker["status"],
                "ingestion_jobs_24h": total_ingestion,
                "ingestion_failures_24h": failed_ingestion,
                "degraded_sources": degraded,
                "backup": "verified" if backup and verification.get("status") == "passed" else "attention_required",
            },
            "active_alerts": [self.serialise(item) for item in self.list_alerts(db, tenant_id, "active", 100)],
            "webhook_configured": bool(os.getenv("FUTURE_ALERT_WEBHOOK_URL", "").strip()),
            "prometheus_endpoint": "/metrics",
            "evaluated_by": actor_id,
        }

    @staticmethod
    def rule(key: str, component: str, severity: str, title: str, message: str, evidence: dict) -> dict:
        return {
            "alert_key": key, "component": component, "severity": severity,
            "title": title, "message": message, "evidence": evidence,
        }

    def list_alerts(self, db: Session, tenant_id: UUID, state: str = "active", limit: int = 100):
        query = db.query(SystemAlert).filter(SystemAlert.tenant_id == tenant_id)
        if state == "active":
            query = query.filter(SystemAlert.status.in_(self.ACTIVE))
        elif state in {"open", "acknowledged", "resolved"}:
            query = query.filter(SystemAlert.status == state)
        return query.order_by(SystemAlert.last_detected_at.desc()).limit(limit).all()

    def acknowledge(self, db: Session, tenant_id: UUID, alert_id: UUID, actor_id: str, note: str):
        alert = db.query(SystemAlert).filter(
            SystemAlert.alert_id == alert_id, SystemAlert.tenant_id == tenant_id
        ).first()
        if not alert:
            return None
        if alert.status == "resolved":
            raise ValueError("Resolved alerts cannot be acknowledged")
        alert.status = "acknowledged"
        alert.acknowledged_at = self.now()
        alert.acknowledged_by = actor_id
        alert.acknowledgement_note = note.strip()
        db.commit()
        db.refresh(alert)
        return alert

    def deliver(self, alert: SystemAlert) -> None:
        url = os.getenv("FUTURE_ALERT_WEBHOOK_URL", "").strip()
        if not url:
            alert.notification_status = "not_configured"
            return
        alert.notification_attempts += 1
        alert.last_notification_at = self.now()
        try:
            response = requests.post(
                url,
                json={
                    "event": "future.system_alert",
                    "alert_id": str(alert.alert_id),
                    "severity": alert.severity,
                    "component": alert.component,
                    "title": alert.title,
                    "message": alert.message,
                    "detected_at": alert.last_detected_at.isoformat(),
                },
                timeout=10,
            )
            response.raise_for_status()
            alert.notification_status = "delivered"
            alert.notification_error = None
        except requests.RequestException as exc:
            alert.notification_status = "failed"
            alert.notification_error = str(exc)[:1000]


monitoring_alert_service = MonitoringAlertService()
