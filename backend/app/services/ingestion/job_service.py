"""
Database-backed ingestion source and job services.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.data_source import DataSource
from app.models.ingestion_failure_event import IngestionFailureEvent
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.ingestion.connector_registry_service import connector_registry_service


class IngestionJobService:
    """
    Creates and updates durable ingestion job state.
    """

    DEFAULT_RETRY_POLICY = {
        "max_attempts": 3,
        "initial_backoff_seconds": 300,
        "backoff_multiplier": 2,
        "max_backoff_seconds": 86400,
        "open_circuit_after_failures": 5,
        "circuit_open_seconds": 3600,
    }

    def get_or_create_source(
        self,
        db: Session,
        source_key: str,
        defaults: Dict[str, Any],
    ) -> DataSource:
        source = (
            db.query(DataSource)
            .filter(DataSource.source_key == source_key)
            .first()
        )

        connector_key = defaults.get("connector_key") or defaults.get("connector_type")

        if source:
            if defaults.get("retry_policy") and not source.retry_policy:
                source.retry_policy = defaults["retry_policy"]
                db.add(source)
                db.flush()
            if not source.connector_definition_id and connector_key:
                definition = connector_registry_service.get_definition_by_key(db, connector_key)
                if definition:
                    connector_registry_service.apply_definition_to_source(source, definition)
                    db.add(source)
                    db.flush()
            return source

        source = DataSource(source_key=source_key, **{k: v for k, v in defaults.items() if k != "connector_key"})
        if connector_key:
            definition = connector_registry_service.get_definition_by_key(db, connector_key)
            if definition:
                connector_registry_service.apply_definition_to_source(source, definition)
        db.add(source)
        db.flush()
        return source

    def create_job(
        self,
        db: Session,
        source: DataSource,
        job_type: str,
        triggered_by: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> IngestionJob:
        job = IngestionJob(
            source_id=source.source_id,
            tenant_id=source.tenant_id,
            job_type=job_type,
            status="queued",
            triggered_by=triggered_by,
            parameters=parameters or {},
            max_attempts=self.retry_policy(source).get("max_attempts", 3),
        )
        db.add(job)
        db.flush()
        return job

    def mark_running(
        self,
        db: Session,
        job: IngestionJob,
        total: int = 0,
    ) -> IngestionJob:
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        job.last_heartbeat_at = now
        job.progress_total = total
        db.add(job)
        db.flush()
        return job

    def update_progress(
        self,
        db: Session,
        job: IngestionJob,
        current: Optional[int] = None,
        total: Optional[int] = None,
        loaded_delta: int = 0,
        failed_delta: int = 0,
        seen_delta: int = 0,
    ) -> IngestionJob:
        if current is not None:
            job.progress_current = current
        if total is not None:
            job.progress_total = total
        job.records_loaded += loaded_delta
        job.records_failed += failed_delta
        job.records_seen += seen_delta
        job.last_heartbeat_at = datetime.now(timezone.utc)
        db.add(job)
        db.flush()
        return job

    def mark_completed(
        self,
        db: Session,
        job: IngestionJob,
        status: str = "completed",
    ) -> IngestionJob:
        now = datetime.now(timezone.utc)
        job.status = status
        job.completed_at = now
        job.last_heartbeat_at = now
        job.next_retry_at = None
        if not job.records_seen or not job.records_loaded:
            durable_record_count = (
                db.query(RawIngestionRecord)
                .filter(RawIngestionRecord.job_id == job.job_id)
                .count()
            )
            if durable_record_count:
                job.records_seen = max(job.records_seen or 0, durable_record_count)
                job.records_loaded = max(job.records_loaded or 0, durable_record_count)
                job.progress_current = max(job.progress_current or 0, job.records_loaded)
                job.progress_total = max(job.progress_total or 0, job.records_seen)
        if job.source:
            job.source.last_success_at = now
            job.source.consecutive_failures = 0
            job.source.circuit_state = "closed"
            job.source.circuit_open_until = None
            db.add(job.source)
        db.add(job)
        db.flush()
        return job

    def mark_failed(
        self,
        db: Session,
        job: IngestionJob,
        error: str,
        failure_stage: str = "execution",
        failure_category: str = "unknown",
        retryable: Optional[bool] = None,
        diagnostic_payload: Optional[Dict[str, Any]] = None,
    ) -> IngestionJob:
        now = datetime.now(timezone.utc)
        policy = self.retry_policy(job.source)
        retryable = self.is_retryable(failure_category) if retryable is None else retryable
        backoff_seconds = self.calculate_backoff_seconds(job.attempt_number, policy)
        can_retry = retryable and job.attempt_number < job.max_attempts

        job.status = "retry_scheduled" if can_retry else "failed"
        job.error_summary = error[:4000]
        job.failure_category = failure_category
        job.failure_stage = failure_stage
        job.failure_details = diagnostic_payload or {}
        job.retry_backoff_seconds = backoff_seconds if can_retry else 0
        job.next_retry_at = now + timedelta(seconds=backoff_seconds) if can_retry else None
        job.completed_at = now
        job.last_heartbeat_at = now

        if job.source:
            job.source.last_failure_at = now
            job.source.consecutive_failures = (job.source.consecutive_failures or 0) + 1
            open_after = policy.get("open_circuit_after_failures", 5)
            if job.source.consecutive_failures >= open_after:
                job.source.circuit_state = "open"
                job.source.circuit_open_until = now + timedelta(
                    seconds=policy.get("circuit_open_seconds", 3600),
                )
            db.add(job.source)

        self.record_failure_event(
            db=db,
            job=job,
            message=error,
            failure_stage=failure_stage,
            failure_category=failure_category,
            retryable=retryable,
            diagnostic_payload=diagnostic_payload or {},
        )
        db.add(job)
        db.flush()
        return job

    def retry_policy(self, source: Optional[DataSource]) -> Dict[str, Any]:
        policy = dict(self.DEFAULT_RETRY_POLICY)
        if source and source.retry_policy:
            policy.update(source.retry_policy)
        config = source.config if source else {}
        if config and isinstance(config.get("retry_policy"), dict):
            policy.update(config["retry_policy"])
        return policy

    def is_retryable(self, failure_category: str) -> bool:
        return failure_category in {
            "network",
            "timeout",
            "rate_limit",
            "temporary_source_error",
            "database",
            "unknown",
        }

    def classify_exception(self, error: Exception) -> str:
        message = str(error).lower()
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if "connection" in message or "network" in message or "dns" in message:
            return "network"
        if "rate" in message and "limit" in message:
            return "rate_limit"
        if "database" in message or "sql" in message:
            return "database"
        if "permission" in message or "unauthor" in message or "forbidden" in message:
            return "permission"
        if "validation" in message or "schema" in message:
            return "validation"
        return "unknown"

    def calculate_backoff_seconds(self, attempt_number: int, policy: Dict[str, Any]) -> int:
        initial = int(policy.get("initial_backoff_seconds", 300))
        multiplier = float(policy.get("backoff_multiplier", 2))
        maximum = int(policy.get("max_backoff_seconds", 86400))
        delay = int(initial * (multiplier ** max(attempt_number - 1, 0)))
        return min(delay, maximum)

    def record_failure_event(
        self,
        db: Session,
        job: IngestionJob,
        message: str,
        failure_stage: str,
        failure_category: str,
        retryable: bool,
        diagnostic_payload: Optional[Dict[str, Any]] = None,
    ) -> IngestionFailureEvent:
        event = IngestionFailureEvent(
            job_id=job.job_id,
            source_id=job.source_id,
            tenant_id=job.tenant_id,
            failure_stage=failure_stage,
            failure_category=failure_category,
            severity="error",
            message=message[:4000],
            retryable="true" if retryable else "false",
            attempt_number=job.attempt_number,
            next_retry_at=job.next_retry_at,
            diagnostic_payload=diagnostic_payload or {},
        )
        db.add(event)
        db.flush()
        return event

    def create_retry_job(
        self,
        db: Session,
        failed_job: IngestionJob,
        triggered_by: Optional[str],
    ) -> IngestionJob:
        if failed_job.status not in {"failed", "retry_scheduled", "completed_with_errors"}:
            raise ValueError("Only failed or partially failed ingestion jobs can be retried")
        if not failed_job.source:
            raise ValueError("Failed job has no source to retry")

        retry_job = IngestionJob(
            source_id=failed_job.source_id,
            tenant_id=failed_job.tenant_id,
            job_type=failed_job.job_type,
            status="queued",
            triggered_by=triggered_by,
            parameters=failed_job.parameters or {},
            attempt_number=(failed_job.attempt_number or 1) + 1,
            max_attempts=failed_job.max_attempts or self.retry_policy(failed_job.source).get("max_attempts", 3),
            retry_of_job_id=failed_job.job_id,
        )
        db.add(retry_job)
        db.flush()
        return retry_job

    def add_raw_record(
        self,
        db: Session,
        job: IngestionJob,
        record_type: str,
        raw_payload: Dict[str, Any],
        source_record_id: Optional[str] = None,
        storage_uri: Optional[str] = None,
        content_hash: Optional[str] = None,
        validation_status: str = "valid",
        normalised_payload: Optional[Dict[str, Any]] = None,
    ) -> RawIngestionRecord:
        record = RawIngestionRecord(
            job_id=job.job_id,
            source_id=job.source_id,
            tenant_id=job.tenant_id,
            source_record_id=source_record_id,
            record_type=record_type,
            storage_uri=storage_uri,
            content_hash=content_hash,
            validation_status=validation_status,
            raw_payload=raw_payload,
            normalised_payload=normalised_payload or {},
        )
        db.add(record)
        db.flush()
        return record

    def get_job(
        self,
        db: Session,
        job_id: UUID,
    ) -> Optional[IngestionJob]:
        query = db.query(IngestionJob).filter(IngestionJob.job_id == job_id)
        tenant_id = db.info.get("tenant_id")
        if tenant_id:
            query = query.filter(
                or_(
                    IngestionJob.tenant_id == UUID(str(tenant_id)),
                    IngestionJob.tenant_id.is_(None),
                )
            )
        return query.first()


ingestion_job_service = IngestionJobService()
