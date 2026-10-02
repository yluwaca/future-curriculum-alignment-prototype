"""
Compatibility wrapper for StatsSA ingestion.

New code should use statssa_connector.py and the /ingestion APIs. These
functions keep the existing labour-market router operational.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from app.db.session import SessionLocal
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.ingestion.statssa_connector import StatsSAQLFSConnector
from app.services.ingestion.statssa_connector import run_statssa_job


def _job_to_dict(job: IngestionJob) -> Dict:
    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "progress": job.progress_current,
        "total": job.progress_total,
        "success": job.records_loaded,
        "failed": job.records_failed,
        "skipped": 0,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "last_file": None,
        "download_completed": job.status in {"completed", "completed_with_errors"},
        "parse_completed": bool(job.parameters.get("parse")) and job.status in {
            "completed",
            "completed_with_errors",
        },
        "parsed_records": 0,
        "error": job.error_summary,
    }


def start_statssa_job(
    start_year: int = 2010,
    end_year: int = 2025,
    parse: bool = False,
    dry_run: bool = False,
    max_files: Optional[int] = None,
) -> str:
    db = SessionLocal()

    try:
        connector = StatsSAQLFSConnector()
        source = connector.ensure_source(db)
        job = connector_job = None
        from app.services.ingestion.job_service import ingestion_job_service

        connector_job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="statssa_qlfs",
            triggered_by=None,
            parameters={
                "start_year": start_year,
                "end_year": end_year,
                "parse": parse,
                "dry_run": dry_run,
                "max_files": max_files,
            },
        )
        job = connector_job
        db.commit()

        thread = threading.Thread(
            target=run_statssa_job,
            kwargs={
                "job_id": job.job_id,
                "start_year": start_year,
                "end_year": end_year,
                "parse": parse,
                "dry_run": dry_run,
                "max_files": max_files,
            },
            daemon=True,
        )
        thread.start()

        return str(job.job_id)

    finally:
        db.close()


def get_job(job_id: str) -> Optional[Dict]:
    db = SessionLocal()

    try:
        job = (
            db.query(IngestionJob)
            .filter(IngestionJob.job_id == job_id)
            .first()
        )

        if not job:
            return None

        payload = _job_to_dict(job)
        payload["parsed_records"] = (
            db.query(RawIngestionRecord)
            .filter(
                RawIngestionRecord.job_id == job.job_id,
                RawIngestionRecord.record_type == "statssa_qlfs_table",
            )
            .count()
        )
        return payload

    finally:
        db.close()
