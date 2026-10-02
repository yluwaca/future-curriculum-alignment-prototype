"""
Generic job advert file ingestion connector.

This is the first active "current jobs" connector. It accepts local uploads
from CSV, XLSX, JSON, TXT, and PDF files, preserves raw records, and upserts
normalised rows into job_posting for later cleaning and skill extraction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID
from xml.etree import ElementTree

import pdfplumber
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.job_posting import JobPosting
from app.models.raw_ingestion_record import RawIngestionRecord
from app.services.audit_service import log_audit_event
from app.services.ingestion.job_service import ingestion_job_service


JOB_ADVERT_SOURCE_KEY = "job_advert_file_upload"

JOB_POSTING_ALLOWED_FIELDS = {
    "job_id",
    "job_title",
    "job_description",
    "required_skills",
    "education_level",
    "experience_years",
    "region",
    "country",
    "employment_type",
    "salary_min",
    "salary_max",
    "posted_date",
    "closed_date",
    "posting_year",
    "posting_month",
    "posting_quarter",
    "source",
    "source_url",
    "source_id",
    "ingestion_job_id",
}


def stable_hash(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def lower_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    return {clean_text(key).lower().replace(" ", "_"): value for key, value in row.items()}


class JobAdvertFileConnector:
    FIELD_ALIASES = {
        "job_id": ["job_id", "id", "posting_id", "reference", "reference_id", "job_reference", "job_link"],
        "job_title": ["job_title", "title", "position", "role", "job_name"],
        "company": ["company", "company_name", "employer", "organisation", "organization"],
        "region": ["region", "location", "province", "city", "job_location"],
        "country": ["country", "country_code"],
        "description": ["description", "job_description", "body", "summary", "advert", "job_summary"],
        "requirements": ["requirements", "requirement", "qualifications", "minimum_requirements"],
        "skills": ["skills", "required_skills", "skill", "keywords", "skills_desc", "job_skills"],
        "education_level": ["education_level", "education", "qualification", "qualifications_required"],
        "experience_years": ["experience_years", "years_experience", "experience", "minimum_experience"],
        "employment_type": ["employment_type", "job_type", "contract_type", "work_type", "formatted_work_type"],
        "salary_min": ["salary_min", "min_salary", "minimum_salary"],
        "salary_max": ["salary_max", "max_salary", "maximum_salary"],
        "salary": ["salary", "salary_range", "remuneration"],
        "posted_date": ["posted_date", "date_posted", "posting_date", "created_at", "published_at", "listed_time", "original_listed_time", "first_seen"],
        "closed_date": ["closed_date", "closing_date", "expiry_date", "expires_at", "expiry", "closed_time"],
        "source": ["source", "platform", "job_board"],
        "source_url": ["source_url", "url", "job_url", "link", "job_link", "job_posting_url"],
    }

    def ensure_source(self, db: Session):
        return ingestion_job_service.get_or_create_source(
            db=db,
            source_key=JOB_ADVERT_SOURCE_KEY,
            defaults={
                "name": "Generic Job Advert File Upload",
                "source_type": "file_upload",
                "source_category": "current_jobs",
                "connector_type": "job_advert_file_upload",
                "connector_key": "job_advert_file_upload",
                "base_url": None,
                "storage_path": None,
                "refresh_policy": "manual",
                "retry_policy": {
                    "max_attempts": 2,
                    "initial_backoff_seconds": 120,
                    "backoff_multiplier": 2,
                    "max_backoff_seconds": 1800,
                    "open_circuit_after_failures": 5,
                    "circuit_open_seconds": 1800,
                },
                "owner": "system",
                "status": "active",
                "is_authorised": True,
                "config": {
                    "ingestion_group": "current_jobs",
                    "supported_formats": ["csv", "xlsx", "json", "txt", "pdf"],
                },
                "auth_config": {},
            },
        )

    def ingest_upload(
        self,
        db: Session,
        file_bytes: bytes,
        original_filename: str,
        actor_id: str,
        source_label: Optional[str] = None,
        default_region: str = "South Africa",
        default_country: str = "ZA",
    ) -> Dict[str, Any]:
        suffix = Path(original_filename).suffix.lower().lstrip(".")
        if suffix not in {"csv", "xlsx", "json", "txt", "pdf"}:
            raise ValueError("Only CSV, XLSX, JSON, TXT, and PDF job advert uploads are supported")

        source = self.ensure_source(db)
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="job_advert_file_upload",
            triggered_by=actor_id,
            parameters={
                "filename": original_filename,
                "format": suffix,
                "source_label": source_label,
                "default_region": default_region,
                "default_country": default_country,
            },
        )
        db.commit()

        try:
            rows = self.extract_rows(file_bytes, original_filename)
            ingestion_job_service.mark_running(db, job, total=len(rows))
            db.commit()
            inserted = 0
            updated = 0
            skipped = 0
            failed = 0

            for index, row in enumerate(rows, start=1):
                try:
                    normalised = self.normalise_row(
                        row=row,
                        source_label=source_label,
                        default_region=default_region,
                        default_country=default_country,
                        source_file=original_filename,
                        row_index=index,
                    )
                    normalised["source_id"] = source.source_id
                    normalised["ingestion_job_id"] = job.job_id
                    raw_record = RawIngestionRecord(
                        job_id=job.job_id,
                        source_id=source.source_id,
                        tenant_id=source.tenant_id,
                        source_record_id=normalised["job_id"],
                        record_type="job_advert_record",
                        content_hash=stable_hash(json.dumps(row, sort_keys=True, default=str)),
                        validation_status="valid",
                        raw_payload={"source_file": original_filename, "row_index": index, "row": row},
                        normalised_payload=self.jsonable(normalised),
                    )
                    db.add(raw_record)
                    action = self.upsert_job_posting(db, normalised)
                    if action == "inserted":
                        inserted += 1
                    elif action == "updated":
                        updated += 1
                    else:
                        skipped += 1
                    ingestion_job_service.update_progress(db, job, current=index, loaded_delta=1, seen_delta=1)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    job = ingestion_job_service.get_job(db, job.job_id)
                    failed += 1
                    ingestion_job_service.update_progress(db, job, current=index, failed_delta=1, seen_delta=1)
                    job.failure_details = {
                        **(job.failure_details or {}),
                        f"row_{index}": str(exc)[:500],
                    }
                    db.add(job)
                    db.commit()

            ingestion_job_service.mark_completed(db, job, "completed" if failed == 0 else "completed_with_errors")
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="job_advert_ingestion",
                actor_type="human",
                actor_id=actor_id,
                token_id=None,
                source_component="job_advert_file_connector",
                action="job_advert_file_uploaded",
                result="success",
                metadata={
                    "job_id": str(job.job_id),
                    "filename": original_filename,
                    "rows": len(rows),
                    "inserted": inserted,
                    "updated": updated,
                    "failed": failed,
                },
            )
            db.commit()
            return {
                "message": "Job advert file uploaded and processed",
                "job": job,
                "rows_seen": len(rows),
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
            }
        except Exception as exc:
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=str(exc),
                failure_stage="job_advert_file_upload",
                failure_category=ingestion_job_service.classify_exception(exc),
            )
            db.commit()
            raise

    def ingest_csv_path(
        self,
        db: Session,
        file_path: Path,
        actor_id: str,
        source_label: Optional[str] = None,
        default_region: str = "South Africa",
        default_country: str = "ZA",
        start_row: int = 1,
        max_rows: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not file_path.exists():
            raise ValueError(f"Job advert file not found: {file_path}")
        if file_path.suffix.lower() != ".csv":
            raise ValueError("Path-based ingestion currently supports CSV files")

        source = self.ensure_source(db)
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="job_advert_file_path_import",
            triggered_by=actor_id,
            parameters={
                "filename": str(file_path),
                "format": "csv",
                "source_label": source_label,
                "default_region": default_region,
                "default_country": default_country,
                "start_row": start_row,
                "max_rows": max_rows,
            },
        )
        db.commit()

        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        rows_seen = 0
        rows_processed = 0

        try:
            ingestion_job_service.mark_running(db, job, total=max_rows or 0)
            db.commit()
            with file_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    rows_seen += 1
                    if rows_seen < start_row:
                        continue
                    rows_processed += 1
                    if max_rows and rows_processed > max_rows:
                        rows_processed -= 1
                        break
                    try:
                        normalised = self.normalise_row(
                            row=row,
                            source_label=source_label,
                            default_region=default_region,
                            default_country=default_country,
                            source_file=file_path.name,
                            row_index=rows_seen,
                        )
                        normalised["source_id"] = source.source_id
                        normalised["ingestion_job_id"] = job.job_id
                        raw_record = RawIngestionRecord(
                            job_id=job.job_id,
                            source_id=source.source_id,
                            tenant_id=source.tenant_id,
                            source_record_id=normalised["job_id"],
                            record_type="job_advert_record",
                            content_hash=stable_hash(json.dumps(row, sort_keys=True, default=str)),
                            validation_status="valid",
                            raw_payload={"source_file": file_path.name, "row_index": rows_seen, "row": row},
                            normalised_payload=self.jsonable(normalised),
                        )
                        db.add(raw_record)
                        action = self.upsert_job_posting(db, normalised)
                        if action == "inserted":
                            inserted += 1
                        elif action == "updated":
                            updated += 1
                        else:
                            skipped += 1
                        ingestion_job_service.update_progress(
                            db,
                            job,
                            current=rows_processed,
                            loaded_delta=1,
                            seen_delta=1,
                        )
                    except Exception as exc:
                        failed += 1
                        ingestion_job_service.update_progress(
                            db,
                            job,
                            current=rows_processed,
                            failed_delta=1,
                            seen_delta=1,
                        )
                        job.failure_details = {
                            **(job.failure_details or {}),
                            f"row_{rows_seen}": str(exc)[:500],
                        }
                        db.add(job)
                    if rows_processed % 500 == 0:
                        db.commit()
                db.commit()

            ingestion_job_service.mark_completed(db, job, "completed" if failed == 0 else "completed_with_errors")
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="job_advert_ingestion",
                actor_type="human",
                actor_id=actor_id,
                token_id=None,
                source_component="job_advert_file_connector",
                action="job_advert_file_path_imported",
                result="success",
                metadata={
                    "job_id": str(job.job_id),
                    "filename": str(file_path),
                    "rows": rows_processed,
                    "start_row": start_row,
                    "inserted": inserted,
                    "updated": updated,
                    "failed": failed,
                },
            )
            db.commit()
            return {
                "message": "Job advert CSV file imported from local path",
                "job": job,
                "rows_seen": rows_processed,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
            }
        except Exception as exc:
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=str(exc),
                failure_stage="job_advert_file_path_import",
                failure_category=ingestion_job_service.classify_exception(exc),
            )
            db.commit()
            raise

    def enrich_from_linkedin_sidecar_path(
        self,
        db: Session,
        file_path: Path,
        actor_id: str,
        enrichment_type: str,
        start_row: int = 1,
        max_rows: Optional[int] = None,
        preserve_unmatched: bool = False,
    ) -> Dict[str, Any]:
        if enrichment_type not in {"skills", "summary"}:
            raise ValueError("enrichment_type must be either 'skills' or 'summary'")
        if not file_path.exists():
            raise ValueError(f"LinkedIn enrichment file not found: {file_path}")
        if file_path.suffix.lower() != ".csv":
            raise ValueError("LinkedIn enrichment import supports CSV files")

        source = self.ensure_source(db)
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type=f"job_advert_{enrichment_type}_enrichment",
            triggered_by=actor_id,
            parameters={
                "filename": str(file_path),
                "format": "csv",
                "enrichment_type": enrichment_type,
                "start_row": start_row,
                "max_rows": max_rows,
                "preserve_unmatched": preserve_unmatched,
            },
        )
        db.commit()

        rows_processed = 0
        rows_seen = 0
        matched = 0
        updated = 0
        skipped = 0
        failed = 0

        try:
            ingestion_job_service.mark_running(db, job, total=max_rows or 0)
            db.commit()
            posting_lookup = self.build_posting_link_lookup(db)
            with file_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    rows_seen += 1
                    if rows_seen < start_row:
                        continue
                    rows_processed += 1
                    if max_rows and rows_processed > max_rows:
                        rows_processed -= 1
                        break
                    try:
                        job_link = clean_text(row.get("job_link"))
                        if not job_link:
                            skipped += 1
                            if rows_processed % 5000 == 0:
                                ingestion_job_service.update_progress(db, job, current=rows_processed, seen_delta=5000)
                                db.commit()
                            continue
                        posting_id = posting_lookup.get(job_link) or posting_lookup.get(stable_hash(job_link)[:32])
                        posting = db.query(JobPosting).filter(JobPosting.posting_id == posting_id).first() if posting_id else None
                        payload = self.normalise_enrichment_payload(row, enrichment_type)
                        if posting or preserve_unmatched:
                            db.add(
                                RawIngestionRecord(
                                    job_id=job.job_id,
                                    source_id=source.source_id,
                                    tenant_id=source.tenant_id,
                                    source_record_id=stable_hash(job_link)[:32],
                                    record_type=f"job_advert_{enrichment_type}_enrichment_record",
                                    content_hash=stable_hash(json.dumps(row, sort_keys=True, default=str)),
                                    validation_status="valid" if posting else "unmatched",
                                    raw_payload={"source_file": file_path.name, "row_index": rows_seen, "row": row},
                                    normalised_payload=payload,
                                )
                            )
                        if posting:
                            matched += 1
                            if enrichment_type == "summary":
                                summary = clean_text(row.get("job_summary"))
                                if summary and not clean_text(posting.job_description):
                                    posting.job_description = summary
                                elif summary and clean_text(posting.job_description) != summary:
                                    posting.job_description = self.merge_description(posting.job_description, summary)
                            else:
                                skills = self.parse_skills(row.get("job_skills"))
                                if skills:
                                    posting.required_skills = self.merge_required_skills(posting.required_skills, skills)
                            posting.is_processed = False
                            posting.embedding_generated = False
                            db.add(posting)
                            updated += 1
                            ingestion_job_service.update_progress(
                                db,
                                job,
                                current=rows_processed,
                                loaded_delta=1,
                                seen_delta=1,
                            )
                        else:
                            skipped += 1
                    except Exception as exc:
                        failed += 1
                        ingestion_job_service.update_progress(
                            db,
                            job,
                            current=rows_processed,
                            failed_delta=1,
                            seen_delta=1,
                        )
                        job.failure_details = {
                            **(job.failure_details or {}),
                            f"row_{rows_seen}": str(exc)[:500],
                        }
                        db.add(job)
                    if rows_processed % 5000 == 0:
                        job.progress_current = rows_processed
                        job.records_seen = rows_processed
                        job.last_heartbeat_at = datetime.now(timezone.utc)
                        db.add(job)
                        db.commit()
                db.commit()
            job.progress_current = rows_processed
            job.records_seen = rows_processed
            db.add(job)
            db.commit()

            ingestion_job_service.mark_completed(db, job, "completed" if failed == 0 else "completed_with_errors")
            log_audit_event(
                db=db,
                event_layer="application",
                event_type="job_advert_enrichment",
                actor_type="human",
                actor_id=actor_id,
                token_id=None,
                source_component="job_advert_file_connector",
                action=f"job_advert_{enrichment_type}_enriched",
                result="success",
                metadata={
                    "job_id": str(job.job_id),
                    "filename": str(file_path),
                    "enrichment_type": enrichment_type,
                    "rows": rows_processed,
                    "matched": matched,
                    "updated": updated,
                    "skipped": skipped,
                    "failed": failed,
                },
            )
            db.commit()
            return {
                "message": f"Job advert {enrichment_type} enrichment imported from local path",
                "job": job,
                "rows_seen": rows_processed,
                "inserted": 0,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "matched": matched,
            }
        except Exception as exc:
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error=str(exc),
                failure_stage=f"job_advert_{enrichment_type}_enrichment",
                failure_category=ingestion_job_service.classify_exception(exc),
            )
            db.commit()
            raise

    def extract_rows(self, file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
        suffix = Path(filename).suffix.lower()
        if suffix == ".csv":
            text = file_bytes.decode("utf-8-sig", errors="replace")
            return [dict(row) for row in csv.DictReader(io.StringIO(text))]
        if suffix == ".json":
            value = json.loads(file_bytes.decode("utf-8-sig", errors="replace"))
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"content": item} for item in value]
            if isinstance(value, dict):
                for key in ("jobs", "items", "results", "data"):
                    if isinstance(value.get(key), list):
                        return [item if isinstance(item, dict) else {"content": item} for item in value[key]]
                return [value]
        if suffix == ".xlsx":
            return self.extract_xlsx_rows(file_bytes)
        if suffix == ".txt":
            return [{"job_title": Path(filename).stem, "description": file_bytes.decode("utf-8-sig", errors="replace")}]
        if suffix == ".pdf":
            return [{"job_title": Path(filename).stem, "description": self.extract_pdf_text(file_bytes)}]
        return []

    def extract_xlsx_rows(self, file_bytes: bytes) -> List[Dict[str, Any]]:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as workbook:
            shared = self.read_shared_strings(workbook)
            sheet_name = "xl/worksheets/sheet1.xml"
            if sheet_name not in workbook.namelist():
                sheets = [name for name in workbook.namelist() if name.startswith("xl/worksheets/sheet")]
                if not sheets:
                    return []
                sheet_name = sheets[0]
            root = ElementTree.fromstring(workbook.read(sheet_name))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: List[List[str]] = []
        for row in root.findall(".//a:sheetData/a:row", ns):
            values: List[str] = []
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "")
                col_index = self.excel_col_index(re.sub(r"\d+", "", ref))
                while len(values) < col_index:
                    values.append("")
                cell_type = cell.attrib.get("t")
                value_node = cell.find("a:v", ns)
                inline_node = cell.find("a:is/a:t", ns)
                value = ""
                if inline_node is not None and inline_node.text:
                    value = inline_node.text
                elif value_node is not None and value_node.text is not None:
                    value = value_node.text
                    if cell_type == "s":
                        value = shared[int(value)] if value.isdigit() and int(value) < len(shared) else value
                values.append(value)
            rows.append(values)
        if not rows:
            return []
        headers = [clean_text(item) or f"column_{idx + 1}" for idx, item in enumerate(rows[0])]
        return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in rows[1:] if any(clean_text(v) for v in row)]

    @staticmethod
    def read_shared_strings(workbook: zipfile.ZipFile) -> List[str]:
        if "xl/sharedStrings.xml" not in workbook.namelist():
            return []
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        return [clean_text(" ".join(t.text or "" for t in item.findall(".//a:t", ns))) for item in root.findall("a:si", ns)]

    @staticmethod
    def excel_col_index(column: str) -> int:
        result = 0
        for char in column.upper():
            if "A" <= char <= "Z":
                result = result * 26 + ord(char) - ord("A") + 1
        return max(result - 1, 0)

    @staticmethod
    def extract_pdf_text(file_bytes: bytes) -> str:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return "\n\n".join(page.extract_text() or "" for page in pdf.pages)

    def normalise_row(
        self,
        row: Dict[str, Any],
        source_label: Optional[str],
        default_region: str,
        default_country: str,
        source_file: str,
        row_index: int,
    ) -> Dict[str, Any]:
        lowered = lower_keys(row)
        get = lambda name: self.first_value(lowered, self.FIELD_ALIASES[name])
        title = clean_text(get("job_title")) or f"Job advert {row_index}"
        description = "\n".join(
            part for part in [
                clean_text(get("description")),
                clean_text(get("requirements")),
            ] if part
        )
        posted_date = self.parse_date(get("posted_date")) or datetime.now(timezone.utc)
        closed_date = self.parse_date(get("closed_date"))
        job_id = clean_text(get("job_id")) or stable_hash(f"{source_file}:{row_index}:{title}:{description}")[:24]
        if len(job_id) > 100:
            job_id = stable_hash(job_id)[:32]
        salary_min, salary_max = self.parse_salary(get("salary_min"), get("salary_max"), get("salary"))
        skills = self.parse_skills(get("skills"))
        return {
            "job_id": job_id,
            "job_title": title[:255],
            "company": clean_text(get("company")) or None,
            "job_description": description or None,
            "required_skills": {"declared": skills, "raw": clean_text(get("skills"))} if skills or get("skills") else None,
            "education_level": (clean_text(get("education_level")) or None),
            "experience_years": self.parse_int(get("experience_years")),
            "region": (clean_text(get("region")) or default_region or "South Africa")[:100],
            "country": (clean_text(get("country")) or default_country or "ZA")[:2].upper(),
            "employment_type": (clean_text(get("employment_type")) or None),
            "salary_min": salary_min,
            "salary_max": salary_max,
            "posted_date": posted_date,
            "closed_date": closed_date,
            "posting_year": posted_date.year,
            "posting_month": posted_date.month,
            "posting_quarter": ((posted_date.month - 1) // 3) + 1,
            "source": (clean_text(get("source")) or source_label or "file_upload")[:100],
            "source_url": clean_text(get("source_url")) or None,
            "metadata": {"source_file": source_file, "row_index": row_index},
        }

    @staticmethod
    def first_value(row: Dict[str, Any], aliases: Iterable[str]) -> Any:
        for alias in aliases:
            if alias in row and row[alias] not in (None, ""):
                return row[alias]
        return None

    @staticmethod
    def parse_date(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = clean_text(value)
        if not text:
            return None
        if re.fullmatch(r"\d+(?:\.0+)?", text):
            timestamp = float(text)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(text[:19], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def parse_int(value: Any) -> Optional[int]:
        match = re.search(r"\d+", clean_text(value))
        return int(match.group()) if match else None

    @staticmethod
    def parse_salary(min_value: Any, max_value: Any, salary_value: Any) -> tuple[Optional[float], Optional[float]]:
        def money(value: Any) -> Optional[float]:
            match = re.search(r"\d[\d\s,]*(?:\.\d+)?", clean_text(value))
            if not match:
                return None
            return float(match.group().replace(" ", "").replace(",", ""))

        salary_text = clean_text(salary_value)
        found = [float(item.replace(" ", "").replace(",", "")) for item in re.findall(r"\d[\d\s,]*(?:\.\d+)?", salary_text)]
        salary_min = money(min_value) or (min(found) if found else None)
        salary_max = money(max_value) or (max(found) if len(found) > 1 else salary_min)
        return salary_min, salary_max

    @staticmethod
    def parse_skills(value: Any) -> List[str]:
        if isinstance(value, list):
            return [clean_text(item) for item in value if clean_text(item)]
        text = clean_text(value)
        if not text:
            return []
        return [item for item in (clean_text(part) for part in re.split(r"[,;|]", text)) if item]

    def upsert_job_posting(self, db: Session, payload: Dict[str, Any]) -> str:
        existing = db.query(JobPosting).filter(JobPosting.job_id == payload["job_id"]).first()
        values = {key: value for key, value in payload.items() if key in JOB_POSTING_ALLOWED_FIELDS}
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.is_processed = False
            existing.embedding_generated = False
            db.add(existing)
            db.flush()
            return "updated"
        posting = JobPosting(**values)
        db.add(posting)
        db.flush()
        return "inserted"

    def insert_job_posting_if_absent(self, db: Session, payload: Dict[str, Any]) -> str:
        """Insert a normalised job posting without overwriting an existing row.

        Used by bounded, additive imports (for example Adzuna pagination).
        The provider-stable job id is the dedup key: a row that already exists
        is never updated or replaced - the caller is informed via "duplicate".
        """
        existing = db.query(JobPosting).filter(JobPosting.job_id == payload["job_id"]).first()
        if existing:
            return "duplicate"
        values = {key: value for key, value in payload.items() if key in JOB_POSTING_ALLOWED_FIELDS}
        posting = JobPosting(**values)
        db.add(posting)
        db.flush()
        return "inserted"

    @staticmethod
    def build_posting_link_lookup(db: Session) -> Dict[str, Any]:
        lookup: Dict[str, Any] = {}
        rows = (
            db.query(JobPosting.posting_id, JobPosting.job_id, JobPosting.source_url)
            .filter(or_(JobPosting.source_url.isnot(None), JobPosting.job_id.isnot(None)))
            .all()
        )
        for posting_id, job_id, source_url in rows:
            if source_url:
                lookup[source_url] = posting_id
            if job_id:
                lookup[job_id] = posting_id
        return lookup

    def find_posting_by_link(self, db: Session, job_link: str) -> Optional[JobPosting]:
        hashed_link = stable_hash(job_link)[:32]
        return (
            db.query(JobPosting)
            .filter(or_(JobPosting.source_url == job_link, JobPosting.job_id == hashed_link))
            .first()
        )

    @staticmethod
    def normalise_enrichment_payload(row: Dict[str, Any], enrichment_type: str) -> Dict[str, Any]:
        payload = {
            "job_link": clean_text(row.get("job_link")),
            "enrichment_type": enrichment_type,
        }
        if enrichment_type == "summary":
            payload["job_summary"] = clean_text(row.get("job_summary"))
        else:
            payload["job_skills"] = JobAdvertFileConnector.parse_skills(row.get("job_skills"))
        return payload

    @staticmethod
    def merge_description(existing: Optional[str], summary: str) -> str:
        existing_text = clean_text(existing)
        summary_text = clean_text(summary)
        if not existing_text:
            return summary_text
        if not summary_text or summary_text in existing_text:
            return existing_text
        if len(existing_text) >= 4000:
            return existing_text
        return f"{existing_text}\n\nLinkedIn summary: {summary_text}"

    @staticmethod
    def merge_required_skills(existing: Optional[Dict[str, Any]], skills: List[str]) -> Dict[str, Any]:
        payload = dict(existing or {})
        declared = payload.get("declared") or []
        if not isinstance(declared, list):
            declared = [declared]
        seen = {clean_text(item).lower() for item in declared if clean_text(item)}
        for skill in skills:
            key = clean_text(skill).lower()
            if key and key not in seen:
                declared.append(clean_text(skill))
                seen.add(key)
        payload["declared"] = declared
        payload["linkedin_enriched"] = True
        payload["linkedin_enriched_count"] = len(skills)
        return payload

    @staticmethod
    def jsonable(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, dict):
            return {key: JobAdvertFileConnector.jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [JobAdvertFileConnector.jsonable(item) for item in value]
        return value


job_advert_file_connector = JobAdvertFileConnector()
