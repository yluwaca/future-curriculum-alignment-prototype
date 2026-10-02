"""PostgreSQL-backed durable operational job queue and worker."""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.operational_job import OperationalJob
from app.services.processing_orchestrator_service import processing_orchestrator_service


logger = logging.getLogger(__name__)
Handler = Callable[[Session, OperationalJob], Dict[str, Any]]


class OperationalJobService:
    ACTIVE_STATUSES = ("queued", "running", "retry_scheduled")
    TERMINAL_STATUSES = ("completed", "failed", "cancelled")
    COMPUTE_JOB_TYPES = ("model.train.xgboost", "model.train.lstm")

    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{uuid.uuid4().hex[:12]}"
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._threads: Dict[str, threading.Thread] = {}
        self.handlers: Dict[str, Handler] = {
            "processing.readiness": self._run_processing_readiness,
            "processing.full": self._run_processing_full,
            "processing.alignment": self._run_processing_alignment,
            "processing.forecasts": self._run_processing_forecasts,
            "processing.recommendations": self._run_processing_recommendations,
            "processing.validated_regeneration": self._run_validated_regeneration,
            "ingestion.statssa": self._run_statssa_ingestion,
            "ingestion.che_vitalstats": self._run_che_vitalstats_ingestion,
            "ingestion.generic_import": self._run_generic_import,
            "ingestion.curriculum_upload": self._run_curriculum_upload,
            "ingestion.cput_prospectus": self._run_cput_prospectus,
            "model.train.xgboost": self._run_xgboost_training,
            "model.train.lstm": self._run_lstm_training,
            "system.backup.create": self._run_system_backup,
            "system.backup.retention": self._run_backup_retention,
            "system.backup.restore_drill": self._run_backup_restore_drill,
            "system.rollback.application_rehearsal": self._run_application_rollback_rehearsal,
            "system.rollback.database_rehearsal": self._run_database_rollback_rehearsal,
            "skills.extract.evidence": self._run_skill_evidence_extraction,
            "taxonomy.esco.bundle.import": self._run_esco_bundle_import,
        }

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def fingerprint(job_type: str, parameters: Dict[str, Any]) -> str:
        payload = json.dumps(
            {"job_type": job_type, "parameters": parameters},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        db: Session,
        job_type: str,
        requested_by: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        max_attempts: int = 3,
    ) -> tuple[OperationalJob, bool]:
        parameters = jsonable_encoder(parameters or {})
        active_jobs = (
            db.query(OperationalJob)
            .filter(
                OperationalJob.job_type == job_type,
                OperationalJob.status.in_(self.ACTIVE_STATUSES),
            )
            .order_by(OperationalJob.created_at.desc())
            .all()
        )
        requested_fingerprint = self.fingerprint(job_type, parameters)
        for active in active_jobs:
            if self.fingerprint(job_type, active.parameters or {}) == requested_fingerprint:
                return active, False

        key = idempotency_key or (
            f"{job_type}:{self.fingerprint(job_type, parameters)}:"
            f"{uuid.uuid4().hex}"
        )
        job = OperationalJob(
            job_type=job_type,
            status="queued",
            idempotency_key=key,
            requested_by=requested_by,
            parameters=parameters,
            progress_current=0,
            progress_total=100,
            progress_message="Queued and waiting for a worker",
            max_attempts=max(1, min(max_attempts, 10)),
            run_manifest={
                "job_type": job_type,
                "parameters": parameters,
                "requested_at": self.now().isoformat(),
            },
        )
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = (
                db.query(OperationalJob)
                .filter(OperationalJob.idempotency_key == key)
                .first()
            )
            if existing:
                return existing, False
            raise
        db.refresh(job)
        self._wake_event.set()
        return job, True

    def list_jobs(
        self,
        db: Session,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> list[OperationalJob]:
        query = db.query(OperationalJob)
        if status:
            query = query.filter(OperationalJob.status == status)
        return query.order_by(OperationalJob.created_at.desc()).limit(min(limit, 200)).all()

    def get_job(self, db: Session, job_id) -> Optional[OperationalJob]:
        return db.query(OperationalJob).filter(OperationalJob.job_id == job_id).first()

    def retry(
        self,
        db: Session,
        failed_job: OperationalJob,
        requested_by: Optional[str],
    ) -> OperationalJob:
        if failed_job.status not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled jobs can be retried")
        retry_job, _ = self.enqueue(
            db=db,
            job_type=failed_job.job_type,
            requested_by=requested_by,
            parameters=failed_job.parameters or {},
            idempotency_key=f"retry:{failed_job.job_id}:{uuid.uuid4().hex}",
            max_attempts=failed_job.max_attempts,
        )
        retry_job.retry_of_job_id = failed_job.job_id
        db.commit()
        db.refresh(retry_job)
        return retry_job

    def request_cancel(self, db: Session, job: OperationalJob) -> OperationalJob:
        if job.status not in self.ACTIVE_STATUSES:
            raise ValueError("Only active jobs can be cancelled")
        job.cancel_requested_at = self.now()
        if job.status in ("queued", "retry_scheduled"):
            job.status = "cancelled"
            job.completed_at = self.now()
            job.progress_message = "Cancelled before execution"
        db.commit()
        db.refresh(job)
        self._wake_event.set()
        return job

    def start_worker(self) -> None:
        if self._threads and all(thread.is_alive() for thread in self._threads.values()):
            return
        self._stop_event.clear()
        for lane in ("operations", "compute"):
            existing = self._threads.get(lane)
            if existing and existing.is_alive():
                continue
            thread = threading.Thread(
                target=self._worker_loop,
                args=(lane,),
                name=f"future-{lane}-worker",
                daemon=True,
            )
            self._threads[lane] = thread
            thread.start()
        logger.info("[JOBS] Operational worker lanes started: %s", self.worker_id)

    def stop_worker(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        for thread in self._threads.values():
            thread.join(timeout=10)
        logger.info("[JOBS] Operational worker lanes stopped: %s", self.worker_id)

    def worker_status(self) -> Dict[str, Any]:
        lane_status = {
            lane: ("running" if thread.is_alive() else "stopped")
            for lane, thread in self._threads.items()
        }
        return {
            "worker_id": self.worker_id,
            "status": (
                "running"
                if lane_status and all(value == "running" for value in lane_status.values())
                else "stopped"
            ),
            "lanes": lane_status,
        }

    def _worker_loop(self, lane: str) -> None:
        try:
            self._recover_stale_jobs()
        except Exception:
            logger.exception("[JOBS] Stale-job recovery failed; worker will retry")
        last_recovery_check = time.monotonic()
        while not self._stop_event.is_set():
            try:
                if time.monotonic() - last_recovery_check >= 30:
                    self._recover_stale_jobs()
                    last_recovery_check = time.monotonic()
                job_id = self._claim_next_job(lane)
                if job_id:
                    self._execute_job(job_id)
                    continue
            except Exception:
                logger.exception("[JOBS] Worker polling failed; retrying")
                time.sleep(2)
            self._wake_event.wait(timeout=2)
            self._wake_event.clear()

    def _recover_stale_jobs(self) -> None:
        cutoff = self.now() - timedelta(minutes=5)
        with SessionLocal() as db:
            stale = (
                db.query(OperationalJob)
                .filter(
                    OperationalJob.status == "running",
                    or_(
                        OperationalJob.heartbeat_at.is_(None),
                        OperationalJob.heartbeat_at < cutoff,
                    ),
                )
                .all()
            )
            for job in stale:
                job.status = "queued"
                job.worker_id = None
                job.claimed_at = None
                job.progress_message = "Recovered after an interrupted worker"
            if stale:
                db.commit()
                logger.warning("[JOBS] Recovered %s stale jobs", len(stale))

    def _claim_next_job(self, lane: str = "operations"):
        now = self.now()
        with SessionLocal() as db:
            query = db.query(OperationalJob).filter(
                OperationalJob.status.in_(("queued", "retry_scheduled")),
                or_(
                    OperationalJob.next_attempt_at.is_(None),
                    OperationalJob.next_attempt_at <= now,
                ),
            )
            if lane == "compute":
                query = query.filter(OperationalJob.job_type.in_(self.COMPUTE_JOB_TYPES))
            else:
                query = query.filter(~OperationalJob.job_type.in_(self.COMPUTE_JOB_TYPES))
            job = (
                query
                .order_by(OperationalJob.created_at.asc())
                .with_for_update(skip_locked=True)
                .first()
            )
            if not job:
                return None
            job.status = "running"
            job.worker_id = self.worker_id
            job.claimed_at = now
            job.heartbeat_at = now
            job.started_at = job.started_at or now
            job.attempt_number += 1
            job.progress_current = 5
            job.progress_message = "Worker claimed the job"
            job_id = job.job_id
            db.commit()
            return job_id

    def _execute_job(self, job_id) -> None:
        with SessionLocal() as db:
            job = self.get_job(db, job_id)
            if not job:
                return
            handler = self.handlers.get(job.job_type)
            if not handler:
                self._fail_job(db, job, f"Unsupported job type: {job.job_type}")
                return
            try:
                if job.cancel_requested_at:
                    job.status = "cancelled"
                    job.completed_at = self.now()
                    job.progress_message = "Cancelled before execution"
                    db.commit()
                    return
                job.progress_current = 10
                job.progress_message = "Running operational workflow"
                job.heartbeat_at = self.now()
                db.commit()
                result = jsonable_encoder(handler(db, job) or {})
                db.refresh(job)
                job.result = result
                cancelled = bool(job.cancel_requested_at)
                job.status = "cancelled" if cancelled else "completed"
                job.progress_current = 100
                job.progress_message = (
                    "Cancellation recorded after the active stage completed"
                    if cancelled
                    else "Completed successfully"
                )
                job.completed_at = self.now()
                job.heartbeat_at = self.now()
                job.run_manifest = {
                    **(job.run_manifest or {}),
                    "worker_id": self.worker_id,
                    "attempt_number": job.attempt_number,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat(),
                    "result_summary": self._result_summary(result),
                }
                db.commit()
            except Exception as exc:
                db.rollback()
                job = self.get_job(db, job_id)
                if job:
                    self._fail_job(db, job, str(exc))
                logger.exception("[JOBS] Job %s failed", job_id)

    def _fail_job(self, db: Session, job: OperationalJob, message: str) -> None:
        now = self.now()
        job.error_summary = message[:8000]
        job.heartbeat_at = now
        if job.attempt_number < job.max_attempts:
            delay_seconds = min(300, 5 * (2 ** max(0, job.attempt_number - 1)))
            job.status = "retry_scheduled"
            job.next_attempt_at = now + timedelta(seconds=delay_seconds)
            job.progress_message = f"Retry scheduled in {delay_seconds} seconds"
        else:
            job.status = "failed"
            job.completed_at = now
            job.progress_message = "Failed after all retry attempts"
        db.commit()

    @staticmethod
    def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in result.items()
            if key in {"report_id", "report_type", "stage_key", "readiness", "before", "after", "delta"}
        }

    @staticmethod
    def to_dict(job: OperationalJob) -> Dict[str, Any]:
        return {
            "job_id": str(job.job_id),
            "job_type": job.job_type,
            "queue_name": job.queue_name,
            "status": job.status,
            "requested_by": job.requested_by,
            "parameters": job.parameters or {},
            "progress_current": job.progress_current,
            "progress_total": job.progress_total,
            "progress_message": job.progress_message,
            "attempt_number": job.attempt_number,
            "max_attempts": job.max_attempts,
            "retry_of_job_id": str(job.retry_of_job_id) if job.retry_of_job_id else None,
            "result": job.result or {},
            "run_manifest": job.run_manifest or {},
            "error_summary": job.error_summary,
            "worker_id": job.worker_id,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "next_attempt_at": job.next_attempt_at,
            "cancel_requested_at": job.cancel_requested_at,
        }

    def _run_processing_readiness(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        p = job.parameters or {}
        return processing_orchestrator_service.run(
            db=db,
            actor_id=job.requested_by,
            limit=int(p.get("limit", 10000)),
            horizon_periods=int(p.get("horizon_periods", 4)),
            run_analytics=False,
        )

    def _run_processing_full(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        p = job.parameters or {}
        return processing_orchestrator_service.run_full_pipeline(
            db=db,
            actor_id=job.requested_by,
            limit=int(p.get("limit", 10000)),
            horizon_periods=int(p.get("horizon_periods", 4)),
        )

    def _run_processing_alignment(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        version_id = (job.parameters or {}).get("version_id")
        return processing_orchestrator_service.rerun_alignment(
            db=db,
            actor_id=job.requested_by,
            version_id=version_id,
        )

    def _run_processing_forecasts(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        return processing_orchestrator_service.rerun_forecasts(
            db=db,
            actor_id=job.requested_by,
            horizon_periods=int((job.parameters or {}).get("horizon_periods", 4)),
        )

    def _run_processing_recommendations(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        version_id = (job.parameters or {}).get("version_id")
        return processing_orchestrator_service.rerun_recommendations(
            db=db,
            actor_id=job.requested_by,
            version_id=version_id,
        )

    def _run_validated_regeneration(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.validated_regeneration_service import validated_regeneration_service

        job.progress_current = 15
        job.progress_message = "Verifying validated curriculum and approved labour evidence"
        job.heartbeat_at = self.now()
        db.commit()
        return validated_regeneration_service.run(
            db=db,
            actor_id=job.requested_by,
            horizon_periods=int((job.parameters or {}).get("horizon_periods", 4)),
        )

    def _run_statssa_ingestion(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.ingestion.statssa_connector import run_statssa_job

        p = job.parameters or {}
        ingestion_job_id = uuid.UUID(str(p["ingestion_job_id"]))
        job.progress_current = 20
        job.progress_message = "Running StatsSA ingestion"
        job.heartbeat_at = self.now()
        db.commit()
        run_statssa_job(
            job_id=ingestion_job_id,
            start_year=int(p["start_year"]),
            end_year=int(p["end_year"]),
            parse=bool(p.get("parse", False)),
            dry_run=bool(p.get("dry_run", False)),
            max_files=p.get("max_files"),
        )
        return self._ingestion_result(db, ingestion_job_id)

    def _run_che_vitalstats_ingestion(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.ingestion.che_vitalstats_connector import run_che_vitalstats_job

        p = job.parameters or {}
        ingestion_job_id = uuid.UUID(str(p["ingestion_job_id"]))
        job.progress_current = 20
        job.progress_message = "Running CHE VitalStats ingestion"
        job.heartbeat_at = self.now()
        db.commit()
        run_che_vitalstats_job(
            job_id=ingestion_job_id,
            start_year=int(p["start_year"]),
            end_year=int(p["end_year"]),
            parse=bool(p.get("parse", False)),
            dry_run=bool(p.get("dry_run", True)),
            max_files=p.get("max_files"),
        )
        return self._ingestion_result(db, ingestion_job_id)

    def _run_generic_import(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.ingestion.async_import_service import run_async_import

        p = job.parameters or {}
        ingestion_job_id = uuid.UUID(str(p["ingestion_job_id"]))
        job.progress_current = 20
        job.progress_message = "Streaming uploaded records into model-ready storage"
        job.heartbeat_at = self.now()
        db.commit()
        return run_async_import(
            job_id=ingestion_job_id,
            auto_enrich=bool(p.get("auto_enrich", True)),
        )

    def _run_curriculum_upload(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.ingestion.curriculum_durable_service import (
            run_staged_curriculum_upload,
        )

        p = job.parameters or {}
        job.progress_current = 20
        job.progress_message = "Extracting and structuring curriculum evidence"
        job.heartbeat_at = self.now()
        db.commit()
        return run_staged_curriculum_upload(
            db,
            staging_path=str(p["staging_token"]),
            original_filename=str(p["original_filename"]),
            mime_type=p.get("mime_type"),
            actor_id=str(job.requested_by or p.get("actor_id") or "system"),
            actor_type=str(p.get("actor_type") or "human"),
            title=p.get("title"),
            faculty=p.get("faculty"),
            department=p.get("department"),
            programme=p.get("programme"),
            document_key=p.get("document_key"),
            description=p.get("description"),
            metadata=p.get("metadata") or {},
            tenant_id=p.get("tenant_id"),
        )

    def _run_cput_prospectus(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.ingestion.cput_prospectus_connector import (
            cput_prospectus_connector,
        )

        p = job.parameters or {}
        job.progress_current = 20
        job.progress_message = "Discovering and importing CPUT prospectus courses"
        job.heartbeat_at = self.now()
        db.commit()
        result = cput_prospectus_connector.import_faculty(
            db=db,
            actor_id=str(job.requested_by or "system"),
            faculty_code=str(p.get("faculty_code") or "220"),
            max_courses=p.get("max_courses"),
            course_codes=p.get("course_codes") or [],
        )
        ingestion_job = result["job"]
        return {
            "ingestion_job_id": str(ingestion_job.job_id),
            "ingestion_status": ingestion_job.status,
            "faculty_code": result["faculty_code"],
            "courses_discovered": result["courses_discovered"],
            "programmes_imported": result["programmes_imported"],
            "modules_imported": result["modules_imported"],
            "failed_courses": result["failed_courses"],
        }

    def _run_xgboost_training(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        return self._run_candidate_training(db, job, "xgboost")

    def _run_lstm_training(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        return self._run_candidate_training(db, job, "lstm")

    def _run_candidate_training(
        self,
        db: Session,
        job: OperationalJob,
        model_type: str,
    ) -> Dict[str, Any]:
        from app.services.candidate_training_service import candidate_training_service

        job.progress_current = 5
        job.progress_message = "Validating locked dataset readiness and reproducible inputs"
        job.heartbeat_at = self.now()
        db.commit()
        result = candidate_training_service.train(
            db=db,
            model_type=model_type,
            actor_id=str(job.requested_by or "system"),
        )
        return {
            "model_type": model_type,
            "registry_entry_id": result.get("registry_entry_id"),
            "lifecycle_state": result.get("lifecycle_state"),
            "dataset_fingerprint": result.get("dataset_fingerprint"),
            "candidate_artifact": result.get("candidate_artifact") or result.get("model_path"),
            "active_model_updated": False,
            "promotion_required": True,
            "metrics": result,
        }

    def _run_system_backup(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.backup_restore_service import backup_restore_service

        job.progress_current = 10
        job.progress_message = "Creating encrypted PostgreSQL, file, and model backup"
        job.heartbeat_at = self.now()
        db.commit()
        result = backup_restore_service.create_backup(actor_id=job.requested_by)
        return {
            "backup_id": result["backup_id"],
            "manifest_path": result["manifest_path"],
            "backup_mode": result["backup_mode"],
            "encryption": result["encryption"],
            "verification": result["verification"],
            "components": result["components"],
            "database_counts": result["database_counts"],
        }

    def _run_backup_retention(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.backup_restore_service import backup_restore_service

        job.progress_current = 20
        job.progress_message = "Applying recoverable backup retention policy"
        job.heartbeat_at = self.now()
        db.commit()
        return backup_restore_service.apply_retention(actor_id=job.requested_by)

    def _run_backup_restore_drill(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.backup_restore_service import backup_restore_service

        job.progress_current = 10
        job.progress_message = "Restoring the latest encrypted backup into an isolated temporary database"
        job.heartbeat_at = self.now()
        db.commit()
        return backup_restore_service.run_isolated_restore_drill(actor_id=job.requested_by)

    def _run_application_rollback_rehearsal(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.deployment_rollback_service import deployment_rollback_service

        job.progress_current = 15
        job.progress_message = "Building and verifying an application rollback release bundle"
        job.heartbeat_at = self.now()
        db.commit()
        return deployment_rollback_service.run_application_rehearsal(actor_id=job.requested_by)

    def _run_database_rollback_rehearsal(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.deployment_rollback_service import deployment_rollback_service

        job.progress_current = 10
        job.progress_message = "Rehearsing Alembic downgrade and upgrade in an isolated database"
        job.heartbeat_at = self.now()
        db.commit()
        return deployment_rollback_service.run_database_rehearsal(actor_id=job.requested_by)

    def _run_skill_evidence_extraction(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.skill_harmonisation_service import skill_harmonisation_service

        parameters = job.parameters or {}
        job.progress_current = 10
        job.progress_message = "Extracting candidate mappings from curriculum evidence"
        job.heartbeat_at = self.now()
        db.commit()
        curriculum = skill_harmonisation_service.extract_from_curriculum(
            db=db,
            limit=int(parameters.get("curriculum_limit") or 1000),
        )
        job.progress_current = 45
        job.progress_message = "Extracting candidate mappings from labour-market evidence"
        job.heartbeat_at = self.now()
        db.commit()
        labour_market = skill_harmonisation_service.extract_from_labour_market(
            db=db,
            limit=min(int(parameters.get("labour_market_limit") or 100), 100),
        )
        return {
            "curriculum": curriculum,
            "labour_market": labour_market,
            "all_mappings_remain_candidates": True,
            "human_review_required": True,
        }

    def _run_esco_bundle_import(self, db: Session, job: OperationalJob) -> Dict[str, Any]:
        from app.services.esco_bundle_import_service import esco_bundle_import_service

        parameters = job.parameters or {}
        bundle_id = parameters["bundle_id"]
        total_steps = 10
        current_step = 0

        def on_progress(
            performed: int,
            message: str,
            partial_counts: Dict[str, Any],
        ) -> None:
            nonlocal current_step
            current_step = performed
            job.progress_current = 5 + int(
                90 * min(current_step, total_steps) / total_steps
            )
            job.progress_message = message
            job.heartbeat_at = self.now()
            db.commit()

        job.progress_current = 5
        job.progress_message = "Validating staged ESCO bundle evidence"
        job.heartbeat_at = self.now()
        db.commit()
        result = esco_bundle_import_service.import_bundle(
            db=db,
            bundle_id=bundle_id,
            actor_id=str(job.requested_by or "system"),
            on_progress=on_progress,
        )
        if not result.get("success", True) or result.get("partial"):
            raise RuntimeError(
                f"ESCO bundle import ended partially: {result.get('error') or 'partial status'}"
            )
        return {
            "bundle_id": result.get("bundle_id"),
            "run_id": result.get("run_id"),
            "status": result.get("status"),
            "imported_counts": result.get("imported_counts"),
            "not_modelled_files": result.get("not_modelled_files"),
        }

    @staticmethod
    def _ingestion_result(db: Session, ingestion_job_id: uuid.UUID) -> Dict[str, Any]:
        from app.models.ingestion_job import IngestionJob

        db.expire_all()
        ingestion_job = (
            db.query(IngestionJob)
            .filter(IngestionJob.job_id == ingestion_job_id)
            .first()
        )
        if not ingestion_job:
            raise RuntimeError(f"Ingestion job not found after execution: {ingestion_job_id}")
        return {
            "ingestion_job_id": str(ingestion_job.job_id),
            "ingestion_status": ingestion_job.status,
            "records_seen": ingestion_job.records_seen,
            "records_loaded": ingestion_job.records_loaded,
            "records_failed": ingestion_job.records_failed,
            "progress_current": ingestion_job.progress_current,
            "progress_total": ingestion_job.progress_total,
        }


operational_job_service = OperationalJobService()
