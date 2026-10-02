"""
CHE VitalStats connector for higher-education context ingestion.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from html import unescape
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse
from uuid import UUID

import pandas as pd
import pdfplumber
import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ingestion_job import IngestionJob
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.audit_service import log_audit_event
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.lineage_service import lineage_service
from app.services.ingestion.statssa_parser_service import clean_numeric_value, DEFAULT_CONFIG, make_columns_unique
from app.services.ingestion.table_extraction_service import (
    stable_json_hash,
    table_extraction_service,
    to_jsonable,
)


logger = logging.getLogger(__name__)

CHE_SOURCE_KEY = "che_vitalstats"
CHE_VITALSTATS_URL = "https://www.che.ac.za/publications/vital-stats"


class CHEVitalStatsConnector:
    """
    Discovers, downloads, and optionally extracts tables from CHE VitalStats PDFs.
    """

    def __init__(self) -> None:
        self.download_dir = settings.che_path
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "text/html,application/pdf,application/octet-stream",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    def ensure_source(self, db: Session):
        return ingestion_job_service.get_or_create_source(
            db=db,
            source_key=CHE_SOURCE_KEY,
            defaults={
                "name": "CHE VitalStats Higher Education Context",
                "source_type": "public_pdf",
                "source_category": "higher_education_context",
                "connector_type": "che_vitalstats_pdf",
                "connector_key": "che_vitalstats_pdf",
                "base_url": CHE_VITALSTATS_URL,
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
                "config": {
                    "ingestion_group": "higher_education_context",
                    "publisher": "Council on Higher Education",
                    "source_page": CHE_VITALSTATS_URL,
                },
                "auth_config": {},
            },
        )

    def discover_publications(
        self,
        start_year: int,
        end_year: int,
        max_files: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        response = self.session.get(CHE_VITALSTATS_URL, timeout=30)
        response.raise_for_status()
        html = response.text
        links = self.extract_publication_links(html)
        publications: List[Dict[str, object]] = []
        seen = set()

        for href, label in links:
            url = urljoin(CHE_VITALSTATS_URL, unescape(href))
            if url in seen:
                continue
            seen.add(url)
            filename = self.filename_from_label_or_url(label, url)
            year = self.year_from_text(f"{label} {filename}")
            if year is None or year < start_year or year > end_year:
                continue
            title = self.title_from_filename(label or filename)
            publications.append(
                {
                    "url": url,
                    "filename": filename,
                    "title": title,
                    "year": year,
                    "publisher": "Council on Higher Education",
                    "series": "VitalStats",
                }
            )

        publications.sort(key=lambda item: (int(item["year"]), str(item["filename"])))
        if max_files:
            return publications[:max_files]
        return publications

    @staticmethod
    def extract_publication_links(html: str) -> List[Tuple[str, str]]:
        anchors = re.findall(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            flags=re.I | re.S,
        )
        results: List[Tuple[str, str]] = []
        for href, body in anchors:
            body_text = re.sub(r"<[^>]+>", " ", body)
            body_text = " ".join(unescape(body_text).split())
            href_text = unescape(href)
            is_pdf = ".pdf" in body_text.lower() or ".pdf" in href_text.lower()
            is_download = "/download" in href_text.lower() or "download" in body_text.lower()
            is_vitalstats = "vital" in body_text.lower() or "vital" in href_text.lower()
            if is_pdf and is_download and is_vitalstats:
                results.append((href_text, body_text))
        return results

    @staticmethod
    def filename_from_url(url: str) -> str:
        parsed = urlparse(url)
        name = Path(unquote(parsed.path)).name
        safe = re.sub(r"[^a-zA-Z0-9._ -]+", "_", name).strip()
        return safe or "che_vitalstats.pdf"

    @classmethod
    def filename_from_label_or_url(cls, label: str, url: str) -> str:
        cleaned = re.sub(r"^download\s+", "", label or "", flags=re.I).strip()
        match = re.search(r"([^\\/]+?\.pdf)", cleaned, flags=re.I)
        if match:
            name = match.group(1)
        else:
            name = cls.filename_from_url(url)
        safe = re.sub(r"[^a-zA-Z0-9._ -]+", "_", name).strip()
        return safe or "che_vitalstats.pdf"

    @staticmethod
    def title_from_filename(filename: str) -> str:
        title = Path(filename).stem
        title = re.sub(r"[_-]+", " ", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title or "CHE VitalStats"

    @staticmethod
    def year_from_text(value: str) -> Optional[int]:
        years = [int(match.group()) for match in re.finditer(r"(19|20)\d{2}", value)]
        return years[0] if years else None

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
            response = self.session.get(url, timeout=60, stream=True, allow_redirects=True)
            if response.status_code != 200:
                return "failed", None, None
            with file_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
            return "downloaded", file_path, self.file_hash(file_path)
        except Exception as exc:
            logger.warning("CHE VitalStats download failed for %s: %s", filename, exc)
            return "failed", None, None

    def run(
        self,
        job_id: UUID,
        start_year: int,
        end_year: int,
        parse: bool = False,
        dry_run: bool = True,
        max_files: Optional[int] = None,
    ) -> None:
        db = SessionLocal()
        try:
            job = ingestion_job_service.get_job(db, job_id)
            if not job:
                raise RuntimeError(f"Ingestion job not found: {job_id}")

            publications = self.discover_publications(start_year, end_year, max_files=max_files)
            ingestion_job_service.mark_running(db, job, total=len(publications))
            lineage_service.record_event(
                db=db,
                job_id=job.job_id,
                source_id=job.source_id,
                source_system="CHE VitalStats",
                processing_stage="discovery",
                transformation_description="Discovered CHE VitalStats PDF publications from the CHE website.",
                actor_id=job.triggered_by,
                metadata={
                    "source_page": CHE_VITALSTATS_URL,
                    "start_year": start_year,
                    "end_year": end_year,
                    "total_files": len(publications),
                    "dry_run": dry_run,
                },
            )
            db.commit()

            pdf_record_ids: Dict[Path, UUID] = {}
            for index, publication in enumerate(publications, start=1):
                status = "discovered"
                file_path = None
                content_hash = None

                if not dry_run:
                    status, file_path, content_hash = self.download_file(
                        str(publication["url"]),
                        str(publication["filename"]),
                    )

                existing_record = None
                if not dry_run:
                    duplicate_query = db.query(RawIngestionRecord).filter(
                        RawIngestionRecord.source_id == job.source_id,
                        RawIngestionRecord.record_type == "che_vitalstats_pdf",
                    )
                    if content_hash:
                        existing_record = duplicate_query.filter(
                            RawIngestionRecord.content_hash == content_hash,
                        ).first()
                    if not existing_record:
                        existing_record = duplicate_query.filter(
                            RawIngestionRecord.source_record_id == publication["filename"],
                        ).first()

                if existing_record and existing_record.job_id != job.job_id:
                    status = "duplicate"
                    record = existing_record
                else:
                    record = ingestion_job_service.add_raw_record(
                        db=db,
                        job=job,
                        record_type="che_vitalstats_pdf",
                        source_record_id=str(publication["filename"]),
                        storage_uri=str(file_path) if file_path else str(publication["url"]),
                        content_hash=content_hash,
                        validation_status="valid" if status in {"downloaded", "skipped", "discovered"} else "failed",
                        raw_payload={
                            **publication,
                            "download_status": status,
                            "source_page": CHE_VITALSTATS_URL,
                        },
                        normalised_payload={
                            "series": "VitalStats",
                            "year": publication["year"],
                            "source": "CHE",
                            "publisher": "Council on Higher Education",
                            "context_domain": "higher_education_supply",
                        },
                    )

                if file_path:
                    pdf_record_ids[file_path] = record.record_id

                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=job.source_id,
                    output_record_id=record.record_id,
                    source_system="CHE VitalStats",
                    processing_stage="acquisition",
                    transformation_description="Captured CHE VitalStats source file metadata and storage location.",
                    actor_id=job.triggered_by,
                    metadata={
                        "filename": publication["filename"],
                        "year": publication["year"],
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
                ingestion_job_service.update_progress(
                    db=db,
                    job=job,
                    total=len(publications) + len(pdf_record_ids),
                )
                db.commit()
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
                source_component="ingestion.che_vitalstats",
                action="che_vitalstats_ingestion_completed",
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
                    failure_stage="che_vitalstats_ingestion",
                    failure_category=ingestion_job_service.classify_exception(exc),
                    diagnostic_payload={
                        "connector": "che_vitalstats_pdf",
                        "start_year": start_year,
                        "end_year": end_year,
                        "parse": parse,
                        "dry_run": dry_run,
                        "max_files": max_files,
                        "exception_type": exc.__class__.__name__,
                    },
                )
                db.commit()
            logger.exception("CHE VitalStats ingestion job failed")
            raise
        finally:
            db.close()

    def parse_files(
        self,
        db: Session,
        job: IngestionJob,
        pdf_record_ids: Dict[Path, UUID],
    ) -> None:
        for pdf_file, pdf_record_id in pdf_record_ids.items():
            ingestion_job_service.update_progress(
                db=db,
                job=job,
                current=min((job.progress_current or 0) + 1, job.progress_total or (job.progress_current or 0) + 1),
            )
            db.commit()
            pdf_record = (
                db.query(RawIngestionRecord)
                .filter(RawIngestionRecord.record_id == pdf_record_id)
                .first()
            )
            table_infos = self.extract_tables(pdf_file)
            for table_info in table_infos:
                rows = self.clean_rows(table_info)
                if not rows:
                    continue
                table_payload = {
                    "source_file": pdf_file.name,
                    "page": table_info.get("page"),
                    "table_index": table_info.get("table_index"),
                    "title": table_info.get("title"),
                    "canonical_table": table_info.get("canonical_table"),
                    "year": table_info.get("year"),
                    "series": "VitalStats",
                    "raw_data": to_jsonable(table_info.get("raw_data") or []),
                    "rows": rows,
                }
                record = ingestion_job_service.add_raw_record(
                    db=db,
                    job=job,
                    record_type="che_vitalstats_table",
                    source_record_id=f"{pdf_file.name}:p{table_info.get('page')}:t{table_info.get('table_index')}",
                    storage_uri=str(pdf_file),
                    content_hash=stable_json_hash(table_payload),
                    validation_status="valid",
                    raw_payload=table_payload,
                    normalised_payload={
                        "year": table_info.get("year"),
                        "series": "VitalStats",
                        "title": table_info.get("title"),
                        "canonical_table": table_info.get("canonical_table"),
                        "row_count": len(rows),
                        "column_count": len(rows[0].keys()) if rows else 0,
                        "context_domain": "higher_education_supply",
                    },
                )
                extracted_table = table_extraction_service.create_table_from_dataframe(
                    db=db,
                    job=job,
                    raw_record=record,
                    pdf_file=pdf_file,
                    table_info=table_info,
                    rows=rows,
                )
                lineage_service.record_event(
                    db=db,
                    job_id=job.job_id,
                    source_id=job.source_id,
                    input_record_id=pdf_record.record_id if pdf_record else None,
                    output_record_id=record.record_id,
                    source_system="CHE VitalStats",
                    processing_stage="table_extraction",
                    transformation_description="Extracted semi-structured tables from CHE VitalStats PDF.",
                    actor_id=job.triggered_by,
                    metadata={
                        "source_file": pdf_file.name,
                        "page": table_info.get("page"),
                        "table_index": table_info.get("table_index"),
                        "extracted_table_id": str(extracted_table.table_id),
                        "row_count": len(rows),
                    },
                )
                db.commit()


    def extract_tables(self, pdf_path: Path) -> List[Dict[str, object]]:
        tables_data: List[Dict[str, object]] = []
        year = self.year_from_text(pdf_path.name)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    tables = page.extract_tables()
                    for table_index, table in enumerate(tables):
                        if not table or len(table) < 3:
                            continue
                        title = self.detect_table_title(page_text, table_index + 1)
                        tables_data.append(
                            {
                                "raw_data": table,
                                "page": page_index + 1,
                                "table_index": table_index + 1,
                                "title": title,
                                "canonical_table": self.classify_vitalstats_table(title or page_text),
                                "context_domain": "higher_education_supply",
                                "source_file": pdf_path.name,
                                "year": year,
                                "series_code": "CHE_VITALSTATS",
                                "extraction_method": "pdfplumber",
                            }
                        )
        except Exception as exc:
            logger.warning("CHE VitalStats table extraction failed for %s: %s", pdf_path, exc)
        return tables_data

    def clean_rows(self, table_info: Dict[str, object]) -> List[Dict[str, object]]:
        raw_table = table_info.get("raw_data") or []
        df = pd.DataFrame(raw_table).dropna(how="all").reset_index(drop=True)
        if df.empty:
            return []
        df.columns = [str(column).strip() for column in df.iloc[0]]
        df = df.iloc[1:].reset_index(drop=True)
        df = make_columns_unique(df)
        for col in df.columns:
            df[col] = df[col].apply(
                lambda value: clean_numeric_value(value, DEFAULT_CONFIG["numeric_cleaning"])
            )
        df["meta_year"] = table_info.get("year")
        df["meta_source_file"] = table_info.get("source_file")
        df["meta_table_title"] = table_info.get("title")
        df["meta_canonical_table"] = table_info.get("canonical_table")
        df["meta_context_domain"] = "higher_education_supply"
        return [to_jsonable(row) for row in df.to_dict(orient="records")]

    @staticmethod
    def detect_table_title(page_text: str, table_index: int) -> str:
        lines = [
            re.sub(r"\s+", " ", line).strip()
            for line in (page_text or "").splitlines()
            if line and line.strip()
        ]
        candidates = [
            line for line in lines
            if re.search(r"\btable\b|\bfigure\b|enrol|graduat|throughput|qualification", line, re.I)
            and len(line) <= 180
        ]
        if table_index <= len(candidates):
            return candidates[table_index - 1]
        return "CHE VitalStats extracted table"

    @staticmethod
    def classify_vitalstats_table(text: str) -> str:
        value = (text or "").lower()
        if any(term in value for term in ["enrol", "headcount"]):
            return "che_enrolment"
        if any(term in value for term in ["graduat", "completion"]):
            return "che_graduation"
        if "throughput" in value:
            return "che_throughput"
        if any(term in value for term in ["qualification", "field of study", "cesm"]):
            return "che_programme_context"
        if any(term in value for term in ["institution", "university"]):
            return "che_institution_context"
        return "che_vitalstats_general"


def run_che_vitalstats_job(
    job_id: UUID,
    start_year: int,
    end_year: int,
    parse: bool = False,
    dry_run: bool = True,
    max_files: Optional[int] = None,
) -> None:
    CHEVitalStatsConnector().run(
        job_id=job_id,
        start_year=start_year,
        end_year=end_year,
        parse=parse,
        dry_run=dry_run,
        max_files=max_files,
    )


