"""Live, read-only operational performance measurements for administrators."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.core.metrics import metrics
from app.models.operational_job import OperationalJob

try:
    import psutil
except ImportError:  # pragma: no cover - supported fallback for minimal deployments
    psutil = None


class SystemPerformanceService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    ACTIVE_JOB_STATES = ("queued", "running", "retry_scheduled")
    FAILED_JOB_STATES = ("failed", "cancelled")

    @staticmethod
    def _tone(value: float, warning: float, critical: float) -> str:
        if value >= critical:
            return "critical"
        if value >= warning:
            return "warning"
        return "healthy"

    @staticmethod
    def _duration_seconds(job: OperationalJob) -> float | None:
        if not job.started_at or not job.completed_at:
            return None
        return max(0.0, (job.completed_at - job.started_at).total_seconds())

    @staticmethod
    def _mean(values: Iterable[float]) -> float | None:
        items = list(values)
        return round(mean(items), 2) if items else None

    def _resources(self) -> Dict[str, Any]:
        if psutil is None:
            return {
                "available": False,
                "cpu_percent": None,
                "memory_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "disk_percent": None,
                "disk_used_bytes": None,
                "disk_total_bytes": None,
                "status": "warning",
                "reason": "The optional psutil package is not installed.",
            }
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self.PROJECT_ROOT.anchor or self.PROJECT_ROOT))
        cpu = float(psutil.cpu_percent(interval=None))
        overall = max(cpu, float(memory.percent), float(disk.percent))
        return {
            "available": True,
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(float(memory.percent), 1),
            "memory_used_bytes": int(memory.used),
            "memory_total_bytes": int(memory.total),
            "disk_percent": round(float(disk.percent), 1),
            "disk_used_bytes": int(disk.used),
            "disk_total_bytes": int(disk.total),
            "status": self._tone(overall, 75, 90),
            "thresholds": {"warning_percent": 75, "critical_percent": 90},
        }

    def _latency(self) -> Dict[str, Any]:
        summary = metrics.get_summary()
        response_times = summary.get("response_times") or {}
        samples = sum(int(item.get("count") or 0) for item in response_times.values())
        weighted_average = (
            sum(float(item.get("avg_ms") or 0) * int(item.get("count") or 0) for item in response_times.values())
            / max(samples, 1)
        )
        p95 = max((float(item.get("p95_ms") or 0) for item in response_times.values()), default=0.0)
        slowest = sorted(
            (
                {"path": path, **values}
                for path, values in response_times.items()
            ),
            key=lambda item: float(item.get("p95_ms") or item.get("max_ms") or 0),
            reverse=True,
        )[:5]
        return {
            "average_ms": round(weighted_average, 2),
            "p95_ms": round(p95, 2),
            "samples": samples,
            "status": self._tone(p95, 750, 2000),
            "thresholds": {"warning_p95_ms": 750, "critical_p95_ms": 2000},
            "slowest_endpoints": slowest,
        }

    def _database(self, db: Session) -> Dict[str, Any]:
        active = None
        total = None
        source = "sqlalchemy_pool"
        try:
            row = db.execute(
                text(
                    "SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE state = 'active') AS active "
                    "FROM pg_stat_activity WHERE datname = current_database()"
                )
            ).mappings().one()
            total = int(row["total"] or 0)
            active = int(row["active"] or 0)
            source = "pg_stat_activity"
        except Exception:
            db.rollback()
        pool = engine.pool
        pool_size = int(pool.size()) if hasattr(pool, "size") else None
        checked_out = int(pool.checkedout()) if hasattr(pool, "checkedout") else None
        capacity = max(pool_size or 0, total or 0, 1)
        pressure = round(((active if active is not None else checked_out or 0) / capacity) * 100, 1)
        return {
            "total_connections": total,
            "active_connections": active,
            "pool_size": pool_size,
            "checked_out": checked_out,
            "pressure_percent": pressure,
            "source": source,
            "status": self._tone(pressure, 70, 90),
            "thresholds": {"warning_percent": 70, "critical_percent": 90},
        }

    def _jobs(self, db: Session) -> Dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        queued = db.query(func.count(OperationalJob.job_id)).filter(
            OperationalJob.status.in_(self.ACTIVE_JOB_STATES)
        ).scalar() or 0
        recent = db.query(OperationalJob).filter(OperationalJob.created_at >= cutoff).all()
        failed = sum(1 for job in recent if job.status in self.FAILED_JOB_STATES)
        failure_rate = round((failed / max(len(recent), 1)) * 100, 2)
        backups = [
            duration
            for job in recent
            if job.job_type == "system.backup.create" and job.status == "completed"
            for duration in [self._duration_seconds(job)]
            if duration is not None
        ]
        queue_status = self._tone(float(queued), 10, 30)
        failure_status = self._tone(failure_rate, 10, 25)
        return {
            "queue_depth": int(queued),
            "queue_status": queue_status,
            "jobs_24h": len(recent),
            "failed_jobs_24h": failed,
            "failure_rate_percent": failure_rate,
            "failure_status": failure_status,
            "average_backup_duration_seconds": self._mean(backups),
            "backup_samples_24h": len(backups),
            "thresholds": {
                "queue_warning": 10,
                "queue_critical": 30,
                "failure_warning_percent": 10,
                "failure_critical_percent": 25,
            },
        }

    def summary(self, db: Session) -> Dict[str, Any]:
        request_metrics = metrics.get_summary()
        resources = self._resources()
        latency = self._latency()
        database = self._database(db)
        jobs = self._jobs(db)
        error_rate = float(request_metrics["error_rate"] or 0)
        request_status = self._tone(error_rate, 5, 15)
        statuses = [
            resources["status"],
            latency["status"],
            database["status"],
            jobs["queue_status"],
            jobs["failure_status"],
            request_status,
        ]
        overall = "critical" if "critical" in statuses else "warning" if "warning" in statuses else "healthy"
        return {
            "status": overall,
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": request_metrics["uptime_seconds"],
            "resources": resources,
            "api_latency": latency,
            "database": database,
            "jobs": jobs,
            "request_totals": {
                "requests": request_metrics["total_requests"],
                "errors": request_metrics["total_errors"],
                "error_rate_percent": error_rate,
                "status": request_status,
                "thresholds": {
                    "warning_percent": 5,
                    "critical_percent": 15,
                },
            },
            "interpretation": (
                "Measurements describe this running backend instance and its database. "
                "They reset when the backend restarts and do not replace external infrastructure monitoring."
            ),
        }


system_performance_service = SystemPerformanceService()
