"""
StatsSA QLFS connector for the dynamic ingestion framework.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.audit_service import log_audit_event
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.labour_market_repository import insert_observation
from app.services.ingestion.lineage_service import lineage_service
from app.services.ingestion.statssa_parser_service import StatsSAParserService
from app.services.ingestion.table_extraction_service import (
    stable_json_hash,
    table_extraction_service,
    to_jsonable,
)


logger = logging.getLogger(__name__)

STATSSA_SOURCE_KEY = "statssa_qlfs"
BASE_URL = "https://www.statssa.gov.za/publications/P0211/"
QUARTERS = {
    "Q1": "1stQuarter",
    "Q2": "2ndQuarter",
    "Q3": "3rdQuarter",
    "Q4": "4thQuarter",
}


class StatsSAQLFSConnector:
    """
    Downloads and optionally parses StatsSA QLFS PDF datasets.
    """

    def __init__(self) -> None:
        self.download_dir = Path(settings.STATSSA_DOWNLOAD_PATH).resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/pdf,application/octet-stream",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )
        self.parser = StatsSAParserService()

    def ensure_source(self, db: Session):
        return ingestion_job_service.get_or_create_source(
            db=db,
            source_key=STATSSA_SOURCE_KEY,
            defaults={
                "name": "StatsSA Quarterly Labour Force Survey",
                "source_type": "api_pdf",
                "source_category": "labour_market",
                "connector_type": "statssa_qlfs",
                "connector_key": "statssa_qlfs_pdf",
                "base_url": BASE_URL,
                "storage_path": str(self.download_dir),
                "refresh_policy": "manual",
                "retry_policy": {
                    "max_attempts": 3,
                    "initial_backoff_seconds": 300,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 21600,
                    "open_circuit_after_failures": 5,
                    "circuit_open_seconds": 3600,
                },
                "owner": "system",
                "status": "active",
                "is_authorised": True,
                "config": {},
                "auth_config": {},
            },
        )

    def generate_urls(
        self,
        start_year: int,
        end_year: int,
        max_files: Optional[int] = None,
    ) -> List[Tuple[str, str, int, str]]:
        urls: List[Tuple[str, str, int, str]] = []

        for year in range(start_year, end_year + 1):
            for quarter_code, quarter_label in QUARTERS.items():
                filename = f"P0211{quarter_label}{year}.pdf"
                urls.append((BASE_URL + filename, filename, year, quarter_code))

        if max_files:
            return urls[:max_files]

        return urls

    @staticmethod
    def file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def download_file(self, url: str, filename: str) -> Tuple[str, Optional[Path], Optional[str]]:
        file_path = self.download_dir / filename

        if file_path.exists():
            return "skipped", file_path, self.file_hash(file_path)

        try:
            response = self.session.get(
                url,
                timeout=60,
                stream=True,
                allow_redirects=True,
            )

            if response.status_code != 200:
                return "failed", None, None

            with file_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)

            return "downloaded", file_path, self.file_hash(file_path)

        except Exception as exc:
            logger.warning("StatsSA download failed for %s: %s", filename, exc)
            return "failed", None, None

    def run(
        self,
        job_id: UUID,
        start_year: int,
        end_year: int,
        parse: bool = False,
        dry_run: bool = False,
        max_files: Optional[int] = None,
    ) -> None:
        db = SessionLocal()

        try:
            job = ingestion_job_service.get_job(db, job_id)
            if not job:
                raise RuntimeError(f"Ingestion job not found: {job_id}")

            urls = self.generate_urls(start_year, end_year, max_files=max_files)
            ingestion_job_service.mark_running(db, job, total=len(urls))

            lineage_service.record_event(
                db=db,
                job_id=job.job_id,
                source_id=job.source_id,
                source_system="StatsSA QLFS",
                processing_stage="discovery",
                transformation_description="Generated expected StatsSA QLFS publication URLs.",
                actor_id=job.triggered_by,
                metadata={
                    "start_year": start_year,
                    "end_year": end_year,
                    "total_files": len(urls),
                    "dry_run": dry_run,
                },
            )
            db.commit()

            pdf_record_ids: Dict[Path, UUID] = {}

            for index, (url, filename, year, quarter) in enumerate(urls, start=1):
                status = "discovered"
                file_path = None
                content_hash = None

                if not dry_run:
                    status, file_path, content_hash = self.download_file(url, filename)

                existing_record = None
                if not dry_run:
                    duplicate_query = db.query(RawIngestionRecord).filter(
                        RawIngestionRecord.source_id == job.source_id,
                        RawIngestionRecord.record_type == "statssa_qlfs_pdf",
                    )
                    if content_hash:
                        existing_record = duplicate_query.filter(
                            RawIngestionRecord.content_hash == content_hash,
                        ).first()
                    if not existing_record:
                        existing_record = duplicate_query.filter(
                            RawIngestionRecord.source_record_id == filename,
                        ).first()

                if existing_record and existing_record.job_id != job.job_id:
                    status = "duplicate"
                    record = existing_record
                else:
                    record = ingestion_job_service.add_raw_record(
                        db=db,
                        job=job,
                        record_type="statssa_qlfs_pdf",
                        source_record_id=filename,
                        storage_uri=str(file_path) if file_path else url,
                        content_hash=content_hash,
                        validation_status="valid" if status in {"downloaded", "skipped", "discovered"} else "failed",
                        raw_payload={
                            "url": url,
                            "filename": filename,
                            "year": year,
                            "quarter": quarter,
                            "download_status": status,
                        },
                        normalised_payload={
                            "series": "QLFS",
                            "year": year,
                            "quarter": quarter,
                            "source": "StatsSA",
                        },
                    )
                if file_path:
                    pdf_record_ids[file_path] = record.record_id

                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=job.source_id,
                    output_record_id=record.record_id,
                    source_system="StatsSA QLFS",
                    processing_stage="acquisition",
                    transformation_description="Captured StatsSA QLFS source file metadata and storage location.",
                    actor_id=job.triggered_by,
                    metadata={
                        "filename": filename,
                        "status": status,
                        "duplicate_of_record_id": str(existing_record.record_id) if existing_record else None,
                    },
                )

                ingestion_job_service.update_progress(
                    db=db,
                    job=job,
                    current=index,
                    seen_delta=1,
                    loaded_delta=1 if status in {"downloaded", "skipped", "discovered"} else 0,
                    failed_delta=1 if status == "failed" else 0,
                )
                db.commit()

                if not dry_run:
                    time.sleep(1)

            if parse and not dry_run:
                self.parse_files(db, job, pdf_record_ids)

            final_status = "completed_with_errors" if job.records_failed else "completed"
            ingestion_job_service.mark_completed(db, job, status=final_status)
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="ingestion_job",
                actor_type="human",
                actor_id=job.triggered_by,
                token_id=None,
                source_component="ingestion.statssa",
                action="statssa_ingestion_completed",
                result="success" if final_status == "completed" else "partial",
                metadata={
                    "job_id": str(job.job_id),
                    "status": final_status,
                    "records_loaded": job.records_loaded,
                    "records_failed": job.records_failed,
                },
            )
            db.commit()

        except Exception as exc:
            db.rollback()
            job = ingestion_job_service.get_job(db, job_id)
            if job:
                ingestion_job_service.mark_failed(
                    db=db,
                    job=job,
                    error=str(exc),
                    failure_stage="statssa_ingestion",
                    failure_category=ingestion_job_service.classify_exception(exc),
                    diagnostic_payload={
                        "connector": "statssa_qlfs_pdf",
                        "start_year": start_year,
                        "end_year": end_year,
                        "parse": parse,
                        "dry_run": dry_run,
                        "max_files": max_files,
                        "exception_type": exc.__class__.__name__,
                    },
                )
                db.commit()
            logger.exception("StatsSA ingestion job failed")
            raise

        finally:
            db.close()

    def parse_files(
        self,
        db: Session,
        job: IngestionJob,
        pdf_record_ids: Dict[Path, UUID],
    ) -> None:
        total_files = len(pdf_record_ids)
        ingestion_job_service.update_progress(
            db=db,
            job=job,
            current=0,
            total=total_files,
        )
        db.commit()

        for file_index, (pdf_file, pdf_record_id) in enumerate(pdf_record_ids.items(), start=1):
            pdf_record = (
                db.query(RawIngestionRecord)
                .filter(RawIngestionRecord.record_id == pdf_record_id)
                .first()
            )

            existing_table = (
                db.query(RawIngestionRecord)
                .filter(
                    RawIngestionRecord.source_id == job.source_id,
                    RawIngestionRecord.record_type == "statssa_qlfs_table",
                    RawIngestionRecord.source_record_id.like(f"{pdf_file.name}:%"),
                    RawIngestionRecord.job_id != job.job_id,
                )
                .first()
            )
            if existing_table:
                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=job.source_id,
                    input_record_id=pdf_record.record_id if pdf_record else None,
                    source_system="StatsSA QLFS",
                    processing_stage="table_extraction",
                    transformation_description="Skipped table extraction because this PDF was already extracted.",
                    actor_id=job.triggered_by,
                    metadata={
                        "source_file": pdf_file.name,
                        "existing_record_id": str(existing_table.record_id),
                    },
                )
                ingestion_job_service.update_progress(
                    db=db,
                    job=job,
                    current=file_index,
                    total=total_files,
                )
                db.commit()
                continue

            def page_progress(page_number: int, page_total: int) -> None:
                ingestion_job_service.update_progress(
                    db=db,
                    job=job,
                    current=page_number,
                    total=page_total,
                )
                db.commit()

            tables = self.parser.extract_tables(
                pdf_file,
                page_callback=page_progress,
            )
            inserted_tables = 0

            for table in tables:
                df = self.parser.clean_table(table)

                if df.empty:
                    continue

                rows = [to_jsonable(row) for row in df.to_dict(orient="records")]
                table_payload = {
                    "source_file": pdf_file.name,
                    "page": table.get("page"),
                    "table_index": table.get("table_index"),
                    "title": table.get("title"),
                    "canonical_table": table.get("canonical_table"),
                    "year": table.get("year"),
                    "quarter": table.get("quarter"),
                    "series_code": table.get("series_code"),
                    "raw_data": to_jsonable(table.get("raw_data") or []),
                    "rows": rows,
                }

                record = ingestion_job_service.add_raw_record(
                    db=db,
                    job=job,
                    record_type="statssa_qlfs_table",
                    source_record_id=(
                        f"{pdf_file.name}:p{table.get('page')}:t{table.get('table_index')}"
                    ),
                    storage_uri=str(pdf_file),
                    content_hash=stable_json_hash(table_payload),
                    validation_status="valid",
                    raw_payload=table_payload,
                    normalised_payload={
                        "year": table.get("year"),
                        "quarter": table.get("quarter"),
                        "series_code": table.get("series_code"),
                        "title": table.get("title"),
                        "canonical_table": table.get("canonical_table"),
                        "row_count": len(rows),
                        "column_count": len(rows[0].keys()) if rows else 0,
                    },
                )
                inserted_tables += 1

                extracted_table = table_extraction_service.create_table_from_dataframe(
                    db=db,
                    job=job,
                    raw_record=record,
                    pdf_file=pdf_file,
                    table_info=table,
                    rows=rows,
                )

                for row in rows:
                    year = row.get("meta_year")
                    quarter = row.get("meta_quarter")

                    if not year or not quarter:
                        continue

                    for key, value in row.items():
                        if key.startswith("meta_") or value is None:
                            continue

                        if not isinstance(value, (int, float)):
                            continue

                        insert_observation(
                            db=db,
                            indicator_name=key,
                            year=int(year),
                            quarter=str(quarter),
                            value=float(value),
                            source_file=row.get("meta_source_file") or pdf_file.name,
                        )

                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=job.source_id,
                    input_record_id=pdf_record.record_id if pdf_record else None,
                    output_record_id=record.record_id,
                    source_system="StatsSA QLFS",
                    processing_stage="table_extraction",
                    transformation_description="Extracted structured tables from StatsSA QLFS PDF.",
                    actor_id=job.triggered_by,
                    metadata={
                        "source_file": pdf_file.name,
                        "page": table.get("page"),
                        "table_index": table.get("table_index"),
                        "extracted_table_id": str(extracted_table.table_id),
                        "row_count": len(rows),
                    },
                )

            ingestion_job_service.update_progress(
                db=db,
                job=job,
                current=file_index,
                total=total_files,
                loaded_delta=inserted_tables,
            )
            db.commit()


def run_statssa_job(
    job_id: UUID,
    start_year: int,
    end_year: int,
    parse: bool = False,
    dry_run: bool = False,
    max_files: Optional[int] = None,
) -> None:
    StatsSAQLFSConnector().run(
        job_id=job_id,
        start_year=start_year,
        end_year=end_year,
        parse=parse,
        dry_run=dry_run,
        max_files=max_files,
    )
