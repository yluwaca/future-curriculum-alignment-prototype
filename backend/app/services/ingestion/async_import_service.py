"""Durable execution for importing previously uploaded generic source records."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from app.db.session import SessionLocal
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.generic_import_service import import_job_records
from app.services.ingestion.job_service import ingestion_job_service


logger = logging.getLogger(__name__)


def run_async_import(job_id: UUID, auto_enrich: bool) -> Dict[str, Any]:
    """Stream-import a staged ingestion job and return a durable result summary."""
    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if not job:
            raise RuntimeError(f"Ingestion job not found: {job_id}")

        raw_records = (
            db.query(RawIngestionRecord)
            .filter(RawIngestionRecord.job_id == job.job_id)
            .order_by(RawIngestionRecord.record_id)
            .all()
        )
        if not raw_records:
            raise ValueError("No raw records found")

        def on_progress(processed, total, partial):
            try:
                job.progress_current = processed
                job.progress_total = total
                job.last_heartbeat_at = datetime.now(timezone.utc)
                if partial:
                    job.failure_details = {
                        **(job.failure_details or {}),
                        "import_progress": partial,
                    }
                db.add(job)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not persist import progress for %s", job_id)

        result = import_job_records(db, job_id, raw_records, on_progress=on_progress)
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        imported_rows = int(result.get("total_rows_imported") or 0)
        skipped_files = [item for item in result.get("files", []) if item.get("skipped")]
        job.progress_current = job.progress_total or len(raw_records)
        job.failure_details = {
            **(job.failure_details or {}),
            "import_progress": {
                "files_processed": result["files_processed"],
                "total_rows_imported": result["total_rows_imported"],
                "total_errors": result["total_errors"],
            },
            "import_result": {
                "files_processed": result["files_processed"],
                "total_rows_imported": result["total_rows_imported"],
                "total_errors": result["total_errors"],
            },
        }
        if imported_rows <= 0 and skipped_files:
            message = "No supported records were imported. " + "; ".join(
                f"{item.get('filename', 'file')}: {item.get('reason', 'unsupported')}"
                for item in skipped_files[:5]
            )
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=message,
                failure_stage="generic_import",
                failure_category="unsupported_format",
                diagnostic_payload={"import_result": result},
            )
            db.commit()
            raise ValueError(message)

        job.imported = True
        ingestion_job_service.mark_completed(db=db, job=job)
        db.add(job)
        db.commit()

        enrichment = None
        if auto_enrich and imported_rows > 0:
            try:
                from app.services.vector_enrichment_service import vector_enrichment_service

                enrichment = vector_enrichment_service.enrich_job_postings_batch(
                    db=db,
                    limit=5000,
                    top_skill_k=10,
                    top_occ_k=3,
                    min_skill_score=0.35,
                    min_occ_score=0.35,
                )
            except Exception as exc:
                logger.warning("Auto-enrichment failed for %s: %s", job_id, exc)
                enrichment = {"status": "warning", "error": str(exc)}

        return {
            "ingestion_job_id": str(job_id),
            "ingestion_status": job.status,
            "files_processed": result["files_processed"],
            "total_rows_imported": result["total_rows_imported"],
            "total_errors": result["total_errors"],
            "auto_enrich": auto_enrich,
            "enrichment": enrichment,
        }
    except Exception as exc:
        db.rollback()
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if job and job.status != "failed":
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=str(exc),
                failure_stage="async_import",
                failure_category=ingestion_job_service.classify_exception(exc),
            )
            db.commit()
        logger.exception("Durable generic import failed for %s", job_id)
        raise
    finally:
        db.close()
