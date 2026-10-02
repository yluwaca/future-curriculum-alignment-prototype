"""Generic import service.

Supports CSV, XLSX, JSON, TXT, and PDF files.
Detects file types by extension and parses into records.
Detects data type by CSV headers and imports into appropriate tables.
Routes job posting CSVs to the job advert connector for structured ingestion.
Unrecognised CSVs are stored as generic raw records for later review.
"""
import csv
import hashlib
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.esco_skill import ESCOSkill
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.skill import Skill
from app.models.skill_alias import SkillAlias

log = logging.getLogger(__name__)

CHUNK_SIZE = 5000


# ── Header signatures → importer name ──────────────────────────────
# Ordered by specificity — ESCO first (exact match), then job postings (broader match)
HEADER_SIGNATURES: List[Tuple[frozenset, str]] = [
    (frozenset({"preferredLabel", "conceptUri", "skillType"}), "esco_skills"),
    (frozenset({"preferredLabel", "conceptUri", "code", "inScheme"}), "esco_skill_groups"),
    (frozenset({"preferredLabel", "conceptUri", "code"}), "esco_occupations"),
    (frozenset({"occupationUri", "skillUri"}), "esco_occ_skill_links"),
    # Job postings: at least job_title + company or job_link
    (frozenset({"job_title", "company"}), "job_postings"),
    (frozenset({"job_title", "job_link"}), "job_postings"),
    (frozenset({"title", "company"}), "job_postings"),
    (frozenset({"title", "employer"}), "job_postings"),
]


# ── File parsers (bytes → List[Dict]) ─────────────────────────────

def _parse_csv(data: bytes) -> List[Dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def _parse_xlsx(data: bytes) -> List[Dict[str, str]]:
    import pandas as pd
    buf = io.BytesIO(data)
    df = pd.read_excel(buf, engine="openpyxl", dtype=str)
    df = df.fillna("")
    return [dict(row) for _, row in df.iterrows()]


def _parse_json(data: bytes) -> List[Dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("data", "records", "items", "results", "rows"):
            if key in obj and isinstance(obj[key], list):
                return obj[key]
        return [obj]
    return []


def _parse_txt(data: bytes) -> List[Dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.strip().splitlines()
    if not lines:
        return []
    first_line = lines[0]
    delimiter = "\t"
    if first_line.count("|") > first_line.count("\t"):
        delimiter = "|"
    elif first_line.count(",") > first_line.count("\t"):
        delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return [row for row in reader]


def _parse_pdf(data: bytes) -> List[Dict[str, str]]:
    import pdfplumber
    buf = io.BytesIO(data)
    all_rows: List[Dict[str, str]] = []
    with pdfplumber.open(buf) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(table[0])]
                for row in table[1:]:
                    if not row or all(c is None for c in row):
                        continue
                    record = {}
                    for i, val in enumerate(row):
                        key = headers[i] if i < len(headers) else f"col_{i}"
                        record[key] = str(val).strip() if val is not None else ""
                    all_rows.append(record)
    return all_rows


PARSERS = {
    ".csv": _parse_csv,
    ".xlsx": _parse_xlsx,
    ".xls": _parse_xlsx,
    ".json": _parse_json,
    ".txt": _parse_txt,
    ".pdf": _parse_pdf,
}


# ── Helper ─────────────────────────────────────────────────────────

def _detect_file_type(headers: List[str]) -> Optional[str]:
    normalised = {h.strip() for h in headers}
    for required_cols, importer_name in HEADER_SIGNATURES:
        if required_cols.issubset(normalised):
            return importer_name
    return None


def _normalise_label(label: str) -> str:
    return (label or "").strip().lower()


# ── ESCO Skills importer ────────────────────────────────────────────

def import_esco_skills(db: Session, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    skills_created = 0
    skills_updated = 0
    esco_created = 0
    esco_updated = 0
    aliases_created = 0
    errors = 0

    for row in rows:
        try:
            esco_uri = (row.get("conceptUri") or "").strip()
            label = (row.get("preferredLabel") or "").strip()
            if not esco_uri or not label:
                continue

            skill_type = (row.get("skillType") or "").strip()
            reuse_level = (row.get("reuseLevel") or "").strip()
            description = (row.get("description") or row.get("scopeNote") or row.get("definition") or "").strip()
            status = (row.get("status") or "released").strip()
            alt_labels_raw = (row.get("altLabels") or "").strip()

            existing = db.query(ESCOSkill).filter(ESCOSkill.esco_uri == esco_uri).first()
            if existing:
                existing.preferred_label = label
                existing.skill_type = skill_type
                existing.reuse_level = reuse_level
                if description:
                    existing.description = description
                existing.esco_metadata = {
                    **(existing.esco_metadata or {}),
                    "status": status,
                    "import_source": "generic_import",
                }
                esco_skill = existing
                esco_updated += 1
            else:
                esco_skill = ESCOSkill(
                    esco_uri=esco_uri,
                    preferred_label=label,
                    skill_type=skill_type,
                    reuse_level=reuse_level,
                    description=description,
                    taxonomy_version="esco_1.21",
                    esco_metadata={"status": status, "import_source": "generic_import"},
                )
                db.add(esco_skill)
                db.flush()
                esco_created += 1

            skill_key = f"esco:{_normalise_label(label)}"
            canonical = db.query(Skill).filter(Skill.skill_key == skill_key).first()
            if not canonical:
                canonical = Skill(
                    skill_key=skill_key,
                    name=label,
                    category=skill_type or "esco",
                    description=description,
                    status="active",
                    skill_metadata={"esco_uri": esco_uri, "import_source": "generic_import"},
                )
                db.add(canonical)
                db.flush()
                skills_created += 1
            else:
                if not canonical.description and description:
                    canonical.description = description
                skills_updated += 1

            if esco_skill.skill_id != canonical.skill_id:
                esco_skill.skill_id = canonical.skill_id

            if alt_labels_raw:
                for alias_text in alt_labels_raw.split("\n"):
                    alias_text = alias_text.strip()
                    if not alias_text or len(alias_text) < 2 or len(alias_text) > 250:
                        continue
                    normalised = _normalise_label(alias_text)
                    if len(normalised) > 250:
                        continue
                    existing_alias = (
                        db.query(SkillAlias)
                        .filter(SkillAlias.skill_id == canonical.skill_id, SkillAlias.normalised_alias == normalised)
                        .first()
                    )
                    if not existing_alias:
                        db.add(SkillAlias(
                            skill_id=canonical.skill_id,
                            alias=alias_text,
                            normalised_alias=normalised,
                            source="esco_import",
                        ))
                        aliases_created += 1

        except Exception as exc:
            errors += 1
            log.warning("ESCO skill import error: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    db.flush()
    return {
        "importer": "esco_skills",
        "skills_created": skills_created,
        "skills_updated": skills_updated,
        "esco_skills_created": esco_created,
        "esco_skills_updated": esco_updated,
        "aliases_created": aliases_created,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── ESCO Occupations importer ───────────────────────────────────────

def import_esco_occupations(db: Session, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    created = 0
    updated = 0
    errors = 0

    for row in rows:
        try:
            esco_uri = (row.get("conceptUri") or "").strip()
            label = (row.get("preferredLabel") or "").strip()
            code = (row.get("code") or "").strip()
            if not esco_uri or not label:
                continue

            description = (row.get("description") or row.get("scopeNote") or row.get("definition") or "").strip()
            status = (row.get("status") or "released").strip()
            isco_group = (row.get("iscoGroup") or "").strip()

            existing = db.query(ESCOOccupation).filter(ESCOOccupation.esco_uri == esco_uri).first()
            if existing:
                existing.preferred_label = label
                existing.code = code or existing.code
                if description:
                    existing.description = description
                existing.occupation_metadata = {
                    **(existing.occupation_metadata or {}),
                    "status": status,
                    "isco_group": isco_group,
                    "import_source": "generic_import",
                }
                updated += 1
            else:
                db.add(ESCOOccupation(
                    esco_uri=esco_uri,
                    preferred_label=label,
                    code=code,
                    description=description,
                    status=status,
                    taxonomy_version="esco_1.21",
                    occupation_metadata={"isco_group": isco_group, "import_source": "generic_import"},
                ))
                db.flush()
                created += 1

        except Exception as exc:
            errors += 1
            log.warning("ESCO occupation import error: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    return {
        "importer": "esco_occupations",
        "occupations_created": created,
        "occupations_updated": updated,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── ESCO Occupation-Skill Links importer ────────────────────────────

def import_esco_occ_skill_links(db: Session, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    links_created = 0
    links_skipped = 0
    errors = 0

    occ_rows = db.query(ESCOOccupation.esco_uri, ESCOOccupation.esco_occupation_id).all()
    occ_map = {uri: oid for uri, oid in occ_rows}

    skill_rows = db.query(ESCOSkill.esco_uri, ESCOSkill.esco_skill_id).all()
    skill_map = {uri: sid for uri, sid in skill_rows}

    existing_links = set(
        db.query(ESCOOccupationSkillLink.occupation_id, ESCOOccupationSkillLink.skill_id).all()
    )

    batch = []
    BATCH_SIZE = 2000

    for row in rows:
        try:
            occ_uri = (row.get("occupationUri") or "").strip()
            skill_uri = (row.get("skillUri") or "").strip()
            relation_type = (row.get("relationType") or "essential").strip()
            if not occ_uri or not skill_uri:
                continue

            occ_id = occ_map.get(occ_uri)
            skill_id = skill_map.get(skill_uri)
            if not occ_id or not skill_id:
                links_skipped += 1
                continue

            if (occ_id, skill_id) in existing_links:
                links_skipped += 1
                continue

            batch.append(ESCOOccupationSkillLink(
                occupation_id=occ_id,
                skill_id=skill_id,
                relationship_type=relation_type if relation_type in ("essential", "optional") else "essential",
                skill_type=(row.get("skillType") or "").strip(),
            ))
            existing_links.add((occ_id, skill_id))

            if len(batch) >= BATCH_SIZE:
                db.add_all(batch)
                db.flush()
                links_created += len(batch)
                batch = []

        except Exception as exc:
            errors += 1
            log.warning("ESCO occ-skill link import error: %s", exc)

    if batch:
        try:
            db.add_all(batch)
            db.flush()
            links_created += len(batch)
        except Exception as exc:
            errors += 1
            log.warning("ESCO occ-skill link final batch error: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    return {
        "importer": "esco_occ_skill_links",
        "links_created": links_created,
        "links_skipped": links_skipped,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── ESCO Skill Groups importer ──────────────────────────────────────

def import_esco_skill_groups(db: Session, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    created = 0
    updated = 0
    errors = 0

    for row in rows:
        try:
            esco_uri = (row.get("conceptUri") or "").strip()
            label = (row.get("preferredLabel") or "").strip()
            if not esco_uri or not label:
                continue

            code = (row.get("code") or "").strip()
            description = (row.get("description") or row.get("scopeNote") or "").strip()

            existing = db.query(ESCOSkill).filter(ESCOSkill.esco_uri == esco_uri).first()
            if existing:
                existing.preferred_label = label
                existing.top_concept = True
                existing.description = description or existing.description
                updated += 1
            else:
                db.add(ESCOSkill(
                    esco_uri=esco_uri,
                    preferred_label=label,
                    skill_type="skillGroup",
                    reuse_level="core",
                    description=description,
                    taxonomy_version="esco_1.21",
                    top_concept=True,
                    esco_metadata={"code": code, "import_source": "generic_import"},
                ))
                created += 1

        except Exception as exc:
            errors += 1
            log.warning("ESCO skill group import error: %s", exc)

    db.flush()
    return {
        "importer": "esco_skill_groups",
        "groups_created": created,
        "groups_updated": updated,
        "errors": errors,
        "total_rows": len(rows),
    }


# ── Job Postings importer ──────────────────────────────────────────

def import_job_postings(db: Session, rows: List[Dict[str, str]], filename: str = "unknown", max_rows: Optional[int] = None) -> Dict[str, Any]:
    """Import job postings from CSV rows into job_posting table.

    Uses the JobAdvertFileConnector's normalisation logic to handle
    various column naming conventions (LinkedIn, Indeed, etc.).
    If max_rows is None, imports all rows.
    """
    from app.services.ingestion.job_advert_file_connector import job_advert_file_connector

    inserted = 0
    updated = 0
    errors = 0
    limit = min(len(rows), max_rows) if max_rows else len(rows)

    for index, row in enumerate(rows[:limit], start=1):
        try:
            normalised = job_advert_file_connector.normalise_row(
                row=row,
                source_label="generic_import",
                default_region="South Africa",
                default_country="ZA",
                source_file=filename,
                row_index=index,
            )
            action = job_advert_file_connector.upsert_job_posting(db, normalised)
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
        except Exception as exc:
            errors += 1
            log.warning("Job posting import error: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    db.flush()
    return {
        "importer": "job_postings",
        "postings_inserted": inserted,
        "postings_updated": updated,
        "errors": errors,
        "total_rows": limit,
        "total_available": len(rows),
        "skipped": len(rows) - limit if max_rows and len(rows) > limit else 0,
    }


def import_job_postings_streaming(
    db: Session,
    file_path: Path,
    filename: str = "unknown",
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Stream-import job postings from a CSV file in chunks.

    Reads the CSV line by line (not all at once) to handle large files.
    Commits every CHUNK_SIZE rows to avoid long transactions.
    Calls on_progress(rows_processed, total_estimate, partial_result) after each chunk.
    """
    from app.services.ingestion.job_advert_file_connector import job_advert_file_connector

    inserted = 0
    updated = 0
    errors = 0
    rows_processed = 0

    if not file_path.exists():
        return {"error": f"File not found: {file_path}", "total_rows": 0}

    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        chunk: List[Dict[str, str]] = []

        for row in reader:
            chunk.append(row)
            rows_processed += 1

            if len(chunk) >= CHUNK_SIZE:
                counts = _count_chunk_results(db, chunk, filename, rows_processed - len(chunk) + 1)
                inserted += counts["inserted"]
                updated += counts["updated"]
                errors += counts["errors"]
                db.commit()
                if on_progress:
                    on_progress(rows_processed, None, {
                        "inserted": inserted, "updated": updated, "errors": errors,
                    })
                chunk = []

        if chunk:
            counts = _count_chunk_results(db, chunk, filename, rows_processed - len(chunk) + 1)
            inserted += counts["inserted"]
            updated += counts["updated"]
            errors += counts["errors"]
            db.commit()
            if on_progress:
                on_progress(rows_processed, None, {
                    "inserted": inserted, "updated": updated, "errors": errors,
                })

    return {
        "importer": "job_postings",
        "postings_inserted": inserted,
        "postings_updated": updated,
        "errors": errors,
        "total_rows": rows_processed,
    }


def _count_chunk_results(
    db: Session,
    chunk: List[Dict[str, str]],
    filename: str,
    start_index: int,
) -> Dict[str, int]:
    """Process a chunk of job posting rows and return counts."""
    from app.services.ingestion.job_advert_file_connector import job_advert_file_connector

    inserted = 0
    updated = 0
    errors = 0
    for idx, row in enumerate(chunk, start=start_index):
        try:
            normalised = job_advert_file_connector.normalise_row(
                row=row, source_label="generic_import",
                default_region="South Africa", default_country="ZA",
                source_file=filename, row_index=idx,
            )
            action = job_advert_file_connector.upsert_job_posting(db, normalised)
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
        except Exception:
            errors += 1
            try:
                db.rollback()
            except Exception:
                pass
    return {"inserted": inserted, "updated": updated, "errors": errors}


def import_generic_raw_rows(
    db: Session,
    job_id: Any,
    source_id: Any,
    tenant_id: Any,
    rows: List[Dict[str, str]],
    filename: str,
    record_type: str = "generic_csv_raw",
) -> Dict[str, Any]:
    """Store unrecognised CSV rows as RawIngestionRecord entries.

    This allows any CSV to be imported even if headers don't match
    known patterns. Records are stored for later review or routing.
    """
    from app.models.raw_ingestion_record import RawIngestionRecord

    stored = 0
    errors = 0
    BATCH = 2000
    batch_records = []

    for idx, row in enumerate(rows, start=1):
        try:
            content_hash = hashlib.sha256(
                json.dumps(row, sort_keys=True, default=str).encode()
            ).hexdigest()
            record = RawIngestionRecord(
                job_id=job_id,
                source_id=source_id,
                tenant_id=tenant_id,
                source_record_id=f"{filename}:{idx}",
                record_type=record_type,
                content_hash=content_hash,
                validation_status="pending",
                raw_payload={"filename": filename, "row_index": idx, "row": row},
                normalised_payload={
                    "filename": filename,
                    "row_index": idx,
                    "headers": list(row.keys()),
                    "generic_import": True,
                },
            )
            batch_records.append(record)
            stored += 1

            if len(batch_records) >= BATCH:
                db.add_all(batch_records)
                db.flush()
                batch_records = []
        except Exception as exc:
            errors += 1
            log.warning("Generic raw store error: %s", exc)

    if batch_records:
        try:
            db.add_all(batch_records)
            db.flush()
        except Exception as exc:
            errors += len(batch_records)
            log.warning("Generic raw store final batch error: %s", exc)

    return {
        "importer": "generic_raw",
        "records_stored": stored,
        "errors": errors,
        "total_rows": len(rows),
        "record_type": record_type,
    }


def import_job_records_streaming(
    db: Session,
    job_id: Any,
    raw_records: list,
    on_progress: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Import records from a job using streaming for large CSV files.

    For job posting CSVs over 50K rows, uses streaming import.
    For other formats, falls back to batch import.
    Unrecognised formats are stored as generic raw records.
    """
    from app.models.raw_ingestion_record import RawIngestionRecord
    from app.models.ingestion_job import IngestionJob

    results = []
    total_imported = 0
    total_errors = 0

    for record in raw_records:
        filename = (record.raw_payload or {}).get("filename", "unknown")
        storage_uri = record.storage_uri or ""
        ext = Path(filename).suffix.lower()

        parser = PARSERS.get(ext)
        if not parser:
            results.append({
                "filename": filename,
                "skipped": True,
                "reason": f"Unsupported file type '{ext}'",
            })
            continue

        try:
            file_path = Path(storage_uri)
            if not file_path.exists():
                results.append({"filename": filename, "skipped": True, "reason": "File not found on disk"})
                continue
        except Exception as exc:
            results.append({"filename": filename, "skipped": True, "reason": f"Read error: {exc}"})
            continue

        try:
            if ext == ".csv" and file_path.stat().st_size > 5_000_000:
                first_row = None
                with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as h:
                    reader = csv.DictReader(h)
                    first_row = next(reader, None)
                if first_row:
                    headers = list(first_row.keys())
                    file_type = _detect_file_type(headers)
                    if file_type == "job_postings":
                        def _import_progress(processed, total, partial):
                            if on_progress:
                                on_progress(processed, total, {"filename": filename, **partial})
                        result = import_job_postings_streaming(
                            db, file_path, filename=filename, on_progress=_import_progress,
                        )
                        total_imported += result.get("total_rows", 0)
                        results.append({"filename": filename, "file_type": file_type, "format": ext.lstrip("."), **result})
                        continue
                    elif file_type is None:
                        row_count = 0
                        with open(file_path, "r", encoding="utf-8-sig", errors="replace") as h:
                            for _ in h:
                                row_count += 1
                        row_count = max(0, row_count - 1)
                        result = {
                            "importer": "generic_raw_file_reference",
                            "filename": filename,
                            "file_type": "generic_raw",
                            "format": ext.lstrip("."),
                            "headers": list(first_row.keys()),
                            "row_count_estimate": row_count,
                            "file_size_bytes": file_path.stat().st_size,
                            "storage_uri": str(file_path),
                            "status": "stored_for_later_processing",
                            "total_rows": row_count,
                        }
                        total_imported += row_count
                        results.append(result)
                        continue

            rows = parser(file_path.read_bytes())
            if not rows:
                results.append({"filename": filename, "skipped": True, "reason": f"Empty {ext} file"})
                continue
            headers = list(rows[0].keys())
            file_type = _detect_file_type(headers)
            if not file_type:
                result = {
                    "importer": "generic_raw_file_reference",
                    "filename": filename,
                    "file_type": "generic_raw",
                    "format": ext.lstrip("."),
                    "headers": headers,
                    "row_count_estimate": len(rows),
                    "file_size_bytes": file_path.stat().st_size if file_path.exists() else 0,
                    "storage_uri": str(file_path),
                    "status": "stored_for_later_processing",
                    "total_rows": len(rows),
                }
                total_imported += len(rows)
                results.append(result)
                continue
        except Exception as exc:
            results.append({"filename": filename, "skipped": True, "reason": f"Parse error: {exc}"})
            continue

        importer_fn = IMPORTERS.get(file_type)
        if not importer_fn:
            results.append({"filename": filename, "skipped": True, "reason": f"No importer for type '{file_type}'"})
            continue

        try:
            if file_type == "job_postings":
                result = importer_fn(db, rows, filename=filename)
            else:
                result = importer_fn(db, rows)
            total_imported += result.get("total_rows", 0)
            results.append({"filename": filename, "file_type": file_type, "format": ext.lstrip("."), **result})
        except Exception as exc:
            total_errors += 1
            results.append({"filename": filename, "file_type": file_type, "error": str(exc)})
            log.error("Import failed for %s: %s", filename, exc)
            try:
                db.rollback()
            except Exception:
                pass

    db.commit()

    return {
        "job_id": str(job_id),
        "files_processed": len(results),
        "total_rows_imported": total_imported,
        "total_errors": total_errors,
        "files": results,
    }


# ── Main entry point ────────────────────────────────────────────────

IMPORTERS = {
    "esco_skills": import_esco_skills,
    "esco_occupations": import_esco_occupations,
    "esco_occ_skill_links": import_esco_occ_skill_links,
    "esco_skill_groups": import_esco_skill_groups,
    "job_postings": import_job_postings,
}


def import_job_records(db: Session, job_id, raw_records: list, on_progress: Optional[Callable] = None) -> Dict[str, Any]:
    """Import all raw records from a job. Supports CSV, XLSX, JSON, TXT, PDF."""
    return import_job_records_streaming(db, job_id, raw_records, on_progress=on_progress)
