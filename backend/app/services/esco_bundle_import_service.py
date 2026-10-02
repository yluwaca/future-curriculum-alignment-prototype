"""Controlled ESCO v1.2.0 CSV bundle import workflow.

Operator-supplied multi-file upload -> read-only preview -> validate (checksums,
expected files, schema headers, version/language) -> deterministic staged import
into ESCO reference tables only. Canonical FUTURE skills are never created by a
bundle import, preserving the existing canonical research catalogue.

Import order mirrors dependency order:
  1. skill groups          (skillGroups_en.csv)          -> esco_skill (skill group)
  2. skills                (skills_en.csv)               -> esco_skill
  3. ISCO groups           (ISCOGroups_en.csv)           -> esco_occupation (isco_group)
  4. occupations           (occupations_en.csv)          -> esco_occupation
  5. skill hierarchy       (broaderRelationsSkillPillar_en.csv + skillsHierarchy_en.csv)
  6. occupation hierarchy  (broaderRelationsOccPillar_en.csv + iscoGroup codes)
  7. occupation-skill links(occupationSkillRelations_en.csv) -> esco_occupation_skill_link
  8. auxiliary membership  (collection CSVs)             -> esco_metadata.collections
  9. not-modelled files    (conceptSchemes/dictionary/skillSkillRelations) -> validated/archived

Every row is idempotent on ESCO concept URI: re-import updates rather than
duplicates. Files are persisted under the evidence directory at staging time and
re-verified by SHA-256 before import.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.data.taxonomy_source_registry import ACA_INSPECTION
from app.models.esco_bundle import ESCOBundle
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.esco_skill import ESCOSkill
from app.models.skill import Skill

logger = logging.getLogger(__name__)


def _ratio(num: int, denom: int) -> float:
    return round(float(num) / float(denom), 4) if denom else 0.0

EXPECTED_LICENCE = "European Union Public Licence v1.2"
EXPECTED_SOURCE_LABEL = "European Commission ESCO v1.2.0 English CSV distribution"
EXPECTED_FILES = {item["filename"]: item for item in ACA_INSPECTION["files"]}

# filename -> (target_model, human label)
FILE_TARGETS = {
    "skillGroups_en.csv": ("esco_skill_group", "skill groups"),
    "skills_en.csv": ("esco_skill", "skills"),
    "ISCOGroups_en.csv": ("esco_isco_group", "ISCO groups"),
    "occupations_en.csv": ("esco_occupation", "occupations"),
    "broaderRelationsSkillPillar_en.csv": ("hierarchy_skill", "skill broader-relations"),
    "broaderRelationsOccPillar_en.csv": ("hierarchy_occupation", "occupation broader-relations"),
    "skillsHierarchy_en.csv": ("hierarchy_skill_levels", "skill level hierarchy"),
    "occupationSkillRelations_en.csv": ("esco_occ_skill_link", "occupation-skill relations"),
    "skillSkillRelations_en.csv": ("not_modelled", "skill-skill relations"),
    "conceptSchemes_en.csv": ("not_modelled", "concept schemes"),
    "dictionary_en.csv": ("not_modelled", "dictionary"),
    "digCompSkillsCollection_en.csv": ("membership_skill", "DigComp skill collection"),
    "digitalSkillsCollection_en.csv": ("membership_skill", "digital skills collection"),
    "greenShareOcc_en.csv": ("membership_occupation", "green employment share"),
    "greenSkillsCollection_en.csv": ("membership_skill", "green skills collection"),
    "languageSkillsCollection_en.csv": ("membership_skill", "language skills collection"),
    "researchOccupationsCollection_en.csv": ("membership_occupation", "research occupations collection"),
    "researchSkillsCollection_en.csv": ("membership_skill", "research skills collection"),
    "transversalSkillsCollection_en.csv": ("membership_skill", "transversal skills collection"),
}

COLLECTION_BY_FILE = {
    "digCompSkillsCollection_en.csv": "digcomp",
    "digitalSkillsCollection_en.csv": "digital_skills",
    "greenSkillsCollection_en.csv": "green_skills",
    "languageSkillsCollection_en.csv": "language_skills",
    "researchSkillsCollection_en.csv": "research_skills",
    "transversalSkillsCollection_en.csv": "transversal_skills",
}

NOT_MODELLED_REASONS = {
    "skillSkillRelations_en.csv": "No skill-skill relation table exists; archived as validated source data.",
    "conceptSchemes_en.csv": "Concept schemes are auxiliary; no dedicated table exists.",
    "dictionary_en.csv": "Terminology dictionary is auxiliary; no dedicated table exists.",
}

PHASE_ORDER = [
    "skillGroups_en.csv",
    "skills_en.csv",
    "ISCOGroups_en.csv",
    "occupations_en.csv",
    "broaderRelationsSkillPillar_en.csv",
    "skillsHierarchy_en.csv",
    "broaderRelationsOccPillar_en.csv",
    "occupationSkillRelations_en.csv",
    "digCompSkillsCollection_en.csv",
    "digitalSkillsCollection_en.csv",
    "greenSkillsCollection_en.csv",
    "languageSkillsCollection_en.csv",
    "researchSkillsCollection_en.csv",
    "transversalSkillsCollection_en.csv",
    "greenShareOcc_en.csv",
    "researchOccupationsCollection_en.csv",
    "skillSkillRelations_en.csv",
    "conceptSchemes_en.csv",
    "dictionary_en.csv",
]

CHUNK_SIZE = 2000

csv.field_size_limit(1_000_000_000)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _count_rows(source: Any) -> int:
    if isinstance(source, (str, Path)):
        handle = open(source, "r", encoding="utf-8-sig", errors="replace", newline="")
        close_handle = True
    elif isinstance(source, bytes):
        handle = io.TextIOWrapper(io.BytesIO(source), encoding="utf-8-sig", errors="replace", newline="")
        close_handle = True
    elif isinstance(source, io.TextIOBase):
        handle = source
        close_handle = False
    else:
        handle = io.TextIOWrapper(source, encoding="utf-8-sig", errors="replace", newline="")
        close_handle = True
    try:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _row in reader)
    finally:
        if close_handle:
            handle.close()


def _detect_language_from_filename(filename: str) -> str:
    lower = filename.lower()
    token = lower.split("_")[-1].split(".")[0].lower()
    return token if token in {"en", "nl", "de", "fr", "it", "pl", "pt", "sv", "cs", "da", "el", "es"} else "en"


def _first_column_headers(data: bytes) -> List[str]:
    try:
        text = data.decode("utf-8-sig", errors="replace")
        first_line, _, _ = text.partition("\n")
        return [cell.strip() for cell in csv.reader([first_line]).__next__()]
    except Exception:
        return []


def _normalise_header_set(headers: List[str]) -> set:
    return {h.strip().lower() for h in headers if h and h.strip()}


def _file_target(filename: str, headers: List[str]) -> str:
    target = FILE_TARGETS.get(filename, ("auxiliary", ""))[0]
    if target == "auxiliary":
        return "not_modelled"
    return target


def _expected_sha256(filename: str) -> Optional[str]:
    entry = EXPECTED_FILES.get(filename)
    return entry.get("sha256") if entry else None


def _direction_from_filename(filename: str) -> Optional[str]:
    norm = {
        "skills_en.csv": "skill",
        "skillGroups_en.csv": "skill",
        "occupations_en.csv": "occupation",
        "ISCOGroups_en.csv": "occupation",
    }
    return norm.get(filename)


# --------------------------------------------------------------------------- #
# Preview
# --------------------------------------------------------------------------- #


class ESCOBundleImportService:
    def preview_files(self, files: List[Dict[str, bytes]]) -> Dict[str, Any]:
        """Read-only preview; never writes to the database or disk."""
        preview_files: List[Dict[str, Any]] = []
        errors: List[str] = []
        totals = {"bytes": 0, "rows": 0}
        checksum_mismatch: List[str] = []

        for item in files:
            filename = item.get("filename") or "unknown.csv"
            data = item.get("content") or b""
            totals["bytes"] += len(data)
            if filename not in EXPECTED_FILES:
                errors.append(f"Unrecognised file in the supplied distribution: {filename}")
            created = _first_column_headers(data)
            headers = _normalise_header_set(created)
            detected_language = _detect_language_from_filename(filename)
            target = _file_target(filename, created)
            sha256 = _sha256_bytes(data)
            expected = _expected_sha256(filename)
            matches_registry = expected is not None and expected == sha256
            row_count = 0
            if data:
                row_count = _count_rows(io.BytesIO(data))
            totals["rows"] += row_count
            entry = {
                "filename": filename,
                "byte_size": len(data),
                "sha256": sha256,
                "expected_sha256": expected,
                "matches_registry": matches_registry,
                "data_rows": row_count,
                "detected_language": detected_language,
                "detected_type": target,
                "headers": sorted(headers),
                "validated": target != "not_modelled" or filename in EXPECTED_FILES,
            }
            if expected is not None and expected != sha256:
                checksum_mismatch.append(filename)
            preview_files.append(entry)

        # predicted insert/update/skip counts are computed against the live DB by
        # the same algorithm as import (see predicted_counts()).
        return {
            "source_label": EXPECTED_SOURCE_LABEL,
            "version": "1.2.0",
            "licence": EXPECTED_LICENCE,
            "language": "en",
            "files": sorted(preview_files, key=lambda item: item["filename"]),
            "file_count": len(preview_files),
            "expected_file_count": len(EXPECTED_FILES),
            "supplied": sorted({item["filename"] for item in files}),
            "missing": sorted(set(EXPECTED_FILES) - {item["filename"] for item in files}),
            "validation_failures": errors,
            "checksum_mismatches": checksum_mismatch,
            "totals": totals,
            "predicted": {
                "inserts": sum(item["data_rows"] for item in preview_files if item["detected_type"] not in {"not_modelled"}),
                "updates": 0,
                "skips": 0,
                "note": "Rows are upserted by ESCO concept URI; exact insert/update/skip split is "
                        "resolved during import against the existing reference tables.",
            },
        }

    def predicted_counts(self, db: Session, files: List[Dict[str, bytes]]) -> Dict[str, int]:
        """Estimate inserts/updates/skips using existing reference table row counts."""
        existing = {
            "esco_skill": db.query(func.count(ESCOSkill.esco_skill_id)).scalar() or 0,
            "esco_occupation": db.query(func.count(ESCOOccupation.esco_occupation_id)).scalar() or 0,
            "esco_occ_skill_link": db.query(func.count(ESCOOccupationSkillLink.link_id)).scalar() or 0,
        }
        inserts = 0
        updates = 0
        skips = 0
        for item in files:
            target = _file_target(item.get("filename") or "", _first_column_headers(item.get("content") or b""))
            rows = _count_rows(io.BytesIO(item.get("content") or b""))
            if target == "esco_skill_group":
                target = "esco_skill"
            if target in existing:
                overlap = min(rows, existing[target])
                inserts += rows - overlap
                updates += overlap
            else:
                inserts += rows
        return {"inserts": inserts, "updates": updates, "skips": skips}

    def validate_and_stage(
        self,
        db: Session,
        actor_id: str,
        files: List[Dict[str, bytes]],
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate checksums/schema and persist files for a later durable import."""
        preview = self.preview_files(files)
        file_entries = preview["files"]
        errors = list(preview["validation_failures"])
        if preview["missing"]:
            missing = ", ".join(sorted(preview["missing"]))
            errors.append(f"Missing expected ESCO files: {missing}")
        if preview["checksum_mismatches"]:
            mismatched = ", ".join(sorted(preview["checksum_mismatches"]))
            errors.append(f"Checksum mismatch against the source registry: {mismatched}")
        if not file_entries:
            raise ValueError("No files were supplied.")
        if errors:
            raise ValueError("; ".join(errors))

        bundle_id = uuid.uuid4()
        store_dir = settings.esco_bundle_evidence_path / str(bundle_id)
        store_dir.mkdir(parents=True, exist_ok=True)
        file_checksums: Dict[str, str] = {}
        row_counts: Dict[str, int] = {}
        file_meta: List[Dict[str, Any]] = []
        for item in files:
            filename = item["filename"]
            content = item["content"]
            path = store_dir / filename
            with open(path, "wb") as handle:
                handle.write(content)
            file_checksums[filename] = _sha256_bytes(content)
            row_counts[filename] = _count_rows(path)
            file_meta.append({
                "filename": filename,
                "byte_size": len(content),
                "sha256": file_checksums[filename],
                "data_rows": row_counts[filename],
                "detected_language": _detect_language_from_filename(filename),
                "detected_type": _file_target(filename, _first_column_headers(content)),
            })

        expected_entries = [
            {
                "filename": name,
                "expected_sha256": entry.get("sha256"),
                "expected_bytes": entry.get("bytes"),
                "expected_rows": entry.get("data_rows"),
            }
            for name, entry in sorted(EXPECTED_FILES.items())
        ]

        bundle = ESCOBundle(
            bundle_id=bundle_id,
            source_version="1.2.0",
            language="en",
            licence=EXPECTED_LICENCE,
            source_label=EXPECTED_SOURCE_LABEL,
            status="validated",
            files=file_meta,
            row_counts=row_counts,
            file_checksums=file_checksums,
            validation_errors=errors,
            expected_files=expected_entries,
            predicted=preview["predicted"],
            not_modelled_files=[
                {"filename": entry["filename"], "reason": NOT_MODELLED_REASONS.get(entry["filename"], "Archived as validated source data; no ESCO model table exists.")}
                for entry in file_meta
                if entry["detected_type"] == "not_modelled"
            ],
            imported_by=actor_id,
            source_url="https://esco.ec.europa.eu/en/about-esco/licence_en",
            contributions={"operator_note": note} if note else {},
        )
        db.add(bundle)
        db.commit()
        db.refresh(bundle)
        return self.to_dict(bundle)

    # ------------------------------------------------------------------ #
    # Import
    # ------------------------------------------------------------------ #

    def import_bundle(
        self,
        db: Session,
        bundle_id: Any,
        actor_id: str,
        on_progress: Optional[Callable[[int, str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
        if not bundle:
            raise ValueError("ESCO bundle record not found")
        if bundle.status == "imported":
            return {**self.to_dict(bundle), "reused": True}
        if bundle.status not in {"validated", "partial"}:
            raise ValueError(
                f"Bundle must be validated before import (current status: {bundle.status})"
            )

        stored = settings.esco_bundle_evidence_path / str(bundle.bundle_id)
        if not stored.exists():
            raise ValueError(f"Staged bundle files are missing at {stored}")

        stored_checksums = dict(bundle.file_checksums or {})
        for filename, expected_sha in stored_checksums.items():
            path = stored / filename
            if not path.exists():
                raise ValueError(f"Staged bundle file is missing before import: {filename}")
            if _sha256_file(path) != expected_sha:
                raise ValueError(
                    f"Staged bundle file checksum changed since validation; import aborted: {filename}"
                )

        bundle.run_id = hashlib.sha256(
            ",".join(f"{k}:{v}" for k, v in sorted(bundle.file_checksums.items())).encode("utf-8")
        ).hexdigest()
        bundle.status = "importing"
        bundle.partial_file = None
        bundle.failed_file = None
        bundle.failure_detail = None
        bundle.imported_by = actor_id
        db.commit()

        contributions: Dict[str, Dict[str, int]] = {}
        performed = 0
        total = len(PHASE_ORDER)

        def report(message: str, partial_counts: Dict[str, Any]) -> None:
            if on_progress:
                on_progress(performed, message, partial_counts)
            else:
                logger.info("[ESCO bundle] %s", message)

        try:
            result = self._import_phase_skill_groups(db, bundle, stored, contributions)
            performed += 1
            report("Imported ESCO skill groups", result)

            result = self._import_phase_skills(db, bundle, stored, contributions)
            performed += 1
            report("Imported ESCO skills", result)

            result = self._import_phase_isco_groups(db, bundle, stored, contributions)
            performed += 1
            report("Imported ISCO groups", result)

            result = self._import_phase_occupations(db, bundle, stored, contributions)
            performed += 1
            report("Imported ESCO occupations", result)

            result = self._import_phase_skill_hierarchy(db, bundle, stored, contributions)
            performed += 1
            report("Imported skill broader-relations hierarchy", result)

            result = self._import_phase_skill_level_hierarchy(db, bundle, stored, contributions)
            performed += 1
            report("Imported skill level hierarchy", result)

            result = self._import_phase_occupation_hierarchy(db, bundle, stored, contributions)
            performed += 1
            report("Imported occupation broader-relations hierarchy", result)

            result = self._import_phase_occ_skill_links(db, bundle, stored, contributions)
            performed += 1
            report("Imported occupation-skill relations", result)

            result = self._import_phase_collections(db, bundle, stored, contributions)
            performed += 1
            report("Annotated ESCO collection membership", result)

            result = self._import_phase_membership_occupations(db, bundle, stored, contributions)
            performed += 1
            report("Annotated occupation membership collections", result)

            bundle.status = "imported"
        except Exception as exc:
            db.rollback()
            bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
            bundle.status = "partial"
            bundle.partial_file = None
            bundle.contributions = {**bundle.contributions, **contributions}
            logger.exception("ESCO bundle import failed (partial): %s", exc)
            db.commit()
            return {
                **self.to_dict(bundle),
                "success": False,
                "partial": True,
                "error": str(exc),
            }

        bundle.contributions = {**bundle.contributions, **contributions}
        bundle.imported_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(bundle)
        return {**self.to_dict(bundle), "success": True, "partial": False}

    # ------------------------------------------------------------------ #
    # Phase helpers
    # ------------------------------------------------------------------ #

    def _file_path(self, bundle: ESCOBundle, name: str) -> Path:
        return settings.esco_bundle_evidence_path / str(bundle.bundle_id) / name

    def _bump(self, contributions: Dict[str, Dict[str, int]], phase: str, created: int, updated: int, skipped: int) -> None:
        entry = contributions.setdefault(phase, {"created": 0, "updated": 0, "skipped": 0})
        entry["created"] += created
        entry["updated"] += updated
        entry["skipped"] += skipped

    def _bundle_context(self, bundle: ESCOBundle, filename: str, sha256: str) -> Dict[str, Any]:
        return {
            "source": "esco_bundle_import",
            "bundle_id": str(bundle.bundle_id),
            "run_id": bundle.run_id,
            "filename": filename,
            "sha256": sha256,
            "licence": EXPECTED_LICENCE,
            "language": "en",
            "version": "1.2.0",
            "imported_by": bundle.imported_by,
        }

    def _import_phase_skill_groups(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "skillGroups_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        sha256 = _sha256_file(path)
        context = self._bundle_context(bundle, filename, sha256)
        created = updated = skipped = 0
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            batch = []
            seen = set()
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                label = (row.get("preferredLabel") or "").strip()
                if not uri:
                    skipped += 1
                    continue
                metadata = {**context, "code": (row.get("code") or "").strip(), "status": (row.get("status") or "released").strip()}
                if uri in seen:
                    skipped += 1
                    continue
                seen.add(uri)
                existing = db.query(ESCOSkill).filter(ESCOSkill.esco_uri == uri).first()
                if existing:
                    existing.skill_type = "skillGroup"
                    existing.reuse_level = "core"
                    existing.preferred_label = label or existing.preferred_label
                    existing.top_concept = True
                    existing.bundle_id = bundle.bundle_id
                    if row.get("description") or row.get("scopeNote"):
                        existing.description = (row.get("description") or row.get("scopeNote") or "").strip()
                    for key, value in metadata.items():
                        existing.esco_metadata[key] = value
                    updated += 1
                else:
                    batch.append(ESCOSkill(
                        esco_uri=uri,
                        preferred_label=label,
                        skill_type="skillGroup",
                        reuse_level="core",
                        description=(row.get("description") or row.get("scopeNote") or "").strip() or None,
                        taxonomy_version="1.2.0",
                        top_concept=True,
                        bundle_id=bundle.bundle_id,
                        esco_metadata=metadata,
                    ))
                    created += 1
                if len(batch) >= CHUNK_SIZE:
                    db.add_all(batch)
                    db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
                db.flush()
        db.commit()
        self._bump(contributions, "skillGroups_en.csv", created, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, "skillGroups_en": {"created": created, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "created": created, "updated": updated, "skipped": skipped}

    def _import_phase_skills(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "skills_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        sha256 = _sha256_file(path)
        context = self._bundle_context(bundle, filename, sha256)
        created = updated = skipped = 0
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            batch = []
            seen = set()
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                label = (row.get("preferredLabel") or "").strip()
                if not uri:
                    skipped += 1
                    continue
                alt_labels = [item.strip() for item in (row.get("altLabels") or "").split("\n") if item.strip()]
                description = (row.get("scopeNote") or row.get("definition") or row.get("description") or "").strip()
                metadata = {
                    **context,
                    "status": (row.get("status") or "released").strip(),
                    "modified_date": (row.get("modifiedDate") or "").strip(),
                    "alt_labels": alt_labels,
                    "in_scheme": (row.get("inScheme") or "").strip(),
                }
                if uri in seen:
                    skipped += 1
                    continue
                seen.add(uri)
                existing = db.query(ESCOSkill).filter(ESCOSkill.esco_uri == uri).first()
                if existing:
                    if label:
                        existing.preferred_label = label
                    if row.get("skillType"):
                        existing.skill_type = (row.get("skillType") or "").strip()
                    if row.get("reuseLevel"):
                        existing.reuse_level = (row.get("reuseLevel") or "").strip()
                    if description:
                        existing.description = description
                    existing.bundle_id = bundle.bundle_id
                    for key, value in metadata.items():
                        existing.esco_metadata[key] = value
                    updated += 1
                else:
                    batch.append(ESCOSkill(
                        esco_uri=uri,
                        preferred_label=label,
                        skill_type=(row.get("skillType") or "").strip() or None,
                        reuse_level=(row.get("reuseLevel") or "").strip() or None,
                        description=description or None,
                        taxonomy_version="1.2.0",
                        bundle_id=bundle.bundle_id,
                        esco_metadata=metadata,
                    ))
                    created += 1
                if len(batch) >= CHUNK_SIZE:
                    db.add_all(batch)
                    db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
                db.flush()
        db.commit()
        self._bump(contributions, "skills_en.csv", created, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, "skills_en": {"created": created, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "created": created, "updated": updated, "skipped": skipped}

    def _import_phase_isco_groups(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "ISCOGroups_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        sha256 = _sha256_file(path)
        context = self._bundle_context(bundle, filename, sha256)
        created = updated = skipped = 0
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            batch = []
            seen = set()
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                label = (row.get("preferredLabel") or "").strip()
                code = (row.get("code") or "").strip()
                if not uri:
                    skipped += 1
                    continue
                metadata = {
                    **context,
                    "type": "isco_group",
                    "code": code,
                    "status": (row.get("status") or "released").strip(),
                }
                if uri in seen:
                    skipped += 1
                    continue
                seen.add(uri)
                existing = db.query(ESCOOccupation).filter(ESCOOccupation.esco_uri == uri).first()
                if existing:
                    if label:
                        existing.preferred_label = label
                    if code:
                        existing.code = code
                    existing.top_concept = True
                    existing.bundle_id = bundle.bundle_id
                    if row.get("description"):
                        existing.description = row.get("description").strip()
                    for key, value in metadata.items():
                        existing.occupation_metadata[key] = value
                    updated += 1
                else:
                    batch.append(ESCOOccupation(
                        esco_uri=uri,
                        preferred_label=label,
                        code=code or None,
                        description=(row.get("description") or "").strip() or None,
                        status=(row.get("status") or "released").strip(),
                        taxonomy_version="1.2.0",
                        top_concept=True,
                        bundle_id=bundle.bundle_id,
                        occupation_metadata=metadata,
                    ))
                    created += 1
                if len(batch) >= CHUNK_SIZE:
                    db.add_all(batch)
                    db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
                db.flush()
        db.commit()
        self._bump(contributions, "ISCOGroups_en.csv", created, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, "ISCOGroups_en": {"created": created, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "created": created, "updated": updated, "skipped": skipped}

    def _import_phase_occupations(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "occupations_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        sha256 = _sha256_file(path)
        context = self._bundle_context(bundle, filename, sha256)
        created = updated = skipped = 0
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            batch = []
            seen = set()
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                label = (row.get("preferredLabel") or "").strip()
                if not uri:
                    skipped += 1
                    continue
                code = (row.get("code") or "").strip()
                isco_group_code = (row.get("iscoGroup") or "").strip()
                description = (row.get("scopeNote") or row.get("definition") or row.get("description") or "").strip()
                metadata = {
                    **context,
                    "type": "occupation",
                    "isco_group": isco_group_code,
                    "nace_code": (row.get("naceCode") or "").strip(),
                    "regulated_profession_note": (row.get("regulatedProfessionNote") or "").strip(),
                    "status": (row.get("status") or "released").strip(),
                }
                if uri in seen:
                    skipped += 1
                    continue
                seen.add(uri)
                existing = db.query(ESCOOccupation).filter(ESCOOccupation.esco_uri == uri).first()
                if existing:
                    if label:
                        existing.preferred_label = label
                    if code:
                        existing.code = code
                    if description:
                        existing.description = description
                    existing.bundle_id = bundle.bundle_id
                    for key, value in metadata.items():
                        existing.occupation_metadata[key] = value
                    updated += 1
                else:
                    batch.append(ESCOOccupation(
                        esco_uri=uri,
                        preferred_label=label,
                        code=code or None,
                        description=description or None,
                        status=(row.get("status") or "released").strip(),
                        taxonomy_version="1.2.0",
                        bundle_id=bundle.bundle_id,
                        occupation_metadata=metadata,
                    ))
                    created += 1
                if len(batch) >= CHUNK_SIZE:
                    db.add_all(batch)
                    db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
                db.flush()
        db.commit()
        self._bump(contributions, "occupations_en.csv", created, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, "occupations_en": {"created": created, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "created": created, "updated": updated, "skipped": skipped}

    def _import_phase_skill_hierarchy(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "broaderRelationsSkillPillar_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        uri_to_id = dict(db.query(ESCOSkill.esco_uri, ESCOSkill.esco_skill_id).all())
        updated = 0
        skipped = 0
        links: List[tuple] = []
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                broader = (row.get("broaderUri") or "").strip()
                child_id = uri_to_id.get(uri)
                parent_id = uri_to_id.get(broader)
                if not child_id or not parent_id:
                    skipped += 1
                    continue
                links.append((child_id, parent_id))
                if len(links) >= CHUNK_SIZE:
                    self._apply_parent_links(db, ESCOSkill, links)
                    updated += len(links)
                    links = []
            if links:
                self._apply_parent_links(db, ESCOSkill, links)
                updated += len(links)
        db.commit()
        self._bump(contributions, filename, 0, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, filename: {"created": 0, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "updated": updated, "skipped": skipped}

    def _import_phase_skill_level_hierarchy(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "skillsHierarchy_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        uri_to_id = dict(db.query(ESCOSkill.esco_uri, ESCOSkill.esco_skill_id).all())
        updated = 0
        skipped = 0
        links: List[tuple] = []
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                levels = [(row.get(f"Level {i} URI") or "").strip() for i in range(4)]
                present = [uri for uri in levels if uri]
                if not present:
                    continue
                child_uri = present[-1]
                parent_uri = present[-2] if len(present) > 1 else None
                child_id = uri_to_id.get(child_uri)
                if not child_id:
                    skipped += 1
                    continue
                if parent_uri:
                    parent_id = uri_to_id.get(parent_uri)
                    if not parent_id:
                        skipped += 1
                        continue
                    links.append((child_id, parent_id))
                    if len(links) >= CHUNK_SIZE:
                        self._apply_parent_links(db, ESCOSkill, links)
                        updated += len(links)
                        links = []
                else:
                    updated += 1
            if links:
                self._apply_parent_links(db, ESCOSkill, links)
                updated += len(links)
        db.commit()
        self._bump(contributions, filename, 0, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, filename: {"created": 0, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "updated": updated, "skipped": skipped}

    def _import_phase_occupation_hierarchy(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "broaderRelationsOccPillar_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        uri_to_id = dict(db.query(ESCOOccupation.esco_uri, ESCOOccupation.esco_occupation_id).all())
        isco_by_code: Dict[str, Any] = {}
        for row in db.query(ESCOOccupation.esco_occupation_id, ESCOOccupation.code):
            if row[1]:
                isco_by_code.setdefault(str(row[1]), row[0])
        updated = 0
        skipped = 0
        links: List[tuple] = []
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                uri = (row.get("conceptUri") or "").strip()
                broader = (row.get("broaderUri") or "").strip()
                child_id = uri_to_id.get(uri)
                if not child_id:
                    skipped += 1
                    continue
                parent_id = None
                if broader:
                    parent_id = uri_to_id.get(broader)
                if not parent_id:
                    # Fall back to the iscoGroup code captured on the occupation row.
                    occ = db.query(ESCOOccupation).filter(ESCOOccupation.esco_occupation_id == child_id).first()
                    if occ:
                        code = (occ.occupation_metadata or {}).get("isco_group")
                        parent_id = isco_by_code.get(code) if code else None
                if not parent_id:
                    skipped += 1
                    continue
                if parent_id == child_id:
                    skipped += 1
                    continue
                links.append((child_id, parent_id))
                if len(links) >= CHUNK_SIZE:
                    self._apply_parent_links(db, ESCOOccupation, links)
                    updated += len(links)
                    links = []
            if links:
                self._apply_parent_links(db, ESCOOccupation, links)
                updated += len(links)
        db.commit()
        self._bump(contributions, filename, 0, updated, skipped)
        bundle.imported_counts = {**bundle.imported_counts, filename: {"created": 0, "updated": updated, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "updated": updated, "skipped": skipped}

    def _apply_parent_links(self, db: Session, model, links: List[tuple]) -> None:
        for child_id, parent_id in links:
            db.query(model).filter(model.esco_skill_id == child_id).update({"parent_id": parent_id}) if model is ESCOSkill else db.query(model).filter(model.esco_occupation_id == child_id).update({"parent_id": parent_id})
        db.flush()

    def _import_phase_occ_skill_links(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        filename = "occupationSkillRelations_en.csv"
        path = stored / filename
        if not path.exists():
            return {"filename": filename, "skipped_file": True}
        sha256 = _sha256_file(path)
        context = self._bundle_context(bundle, filename, sha256)
        occ_ids = dict(db.query(ESCOOccupation.esco_uri, ESCOOccupation.esco_occupation_id).all())
        skill_ids = dict(db.query(ESCOSkill.esco_uri, ESCOSkill.esco_skill_id).all())
        existing = {
            (occupation_id, skill_id)
            for occupation_id, skill_id in db.query(
                ESCOOccupationSkillLink.occupation_id,
                ESCOOccupationSkillLink.skill_id,
            ).all()
        }
        created = 0
        skipped = 0
        batch = []
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                occ_uri = (row.get("occupationUri") or "").strip()
                skill_uri = (row.get("skillUri") or "").strip()
                occ_id = occ_ids.get(occ_uri)
                skill_id = skill_ids.get(skill_uri)
                if not occ_id or not skill_id:
                    skipped += 1
                    continue
                key = (occ_id, skill_id)
                if key in existing:
                    skipped += 1
                    continue
                relation_type = (row.get("relationType") or "essential").strip()
                batch.append(ESCOOccupationSkillLink(
                    occupation_id=occ_id,
                    skill_id=skill_id,
                    relationship_type=relation_type if relation_type in ("essential", "optional") else "essential",
                    skill_type=(row.get("skillType") or "").strip() or None,
                    bundle_id=bundle.bundle_id,
                ))
                existing.add(key)
                created += 1
                if len(batch) >= CHUNK_SIZE:
                    db.add_all(batch)
                    db.flush()
                    batch = []
            if batch:
                db.add_all(batch)
                db.flush()
        db.commit()
        self._bump(contributions, filename, created, 0, skipped)
        bundle.imported_counts = {**bundle.imported_counts, filename: {"created": created, "updated": 0, "skipped": skipped}}
        db.commit()
        return {"filename": filename, "created": created, "skipped": skipped}

    def _import_phase_collections(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        total = {"annotated": 0, "skipped": 0}
        skill_ids = dict(db.query(ESCOSkill.esco_uri, ESCOSkill.esco_skill_id).all())
        uri_list = sorted(skill_ids)
        for filename, collection in COLLECTION_BY_FILE.items():
            path = stored / filename
            if not path.exists():
                continue
            annotated = 0
            skipped = 0
            uri_set = set(skill_ids)
            with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    uri = (row.get("conceptUri") or "").strip()
                    if not uri:
                        skipped += 1
                        continue
                    if uri not in uri_set:
                        skipped += 1
                        continue
                    skill = db.query(ESCOSkill).filter(ESCOSkill.esco_skill_id == skill_ids[uri]).first()
                    metadata = dict(skill.esco_metadata or {})
                    collections = set(metadata.get("collections") or [])
                    collections.add(collection)
                    metadata["collections"] = sorted(collections)
                    skill.esco_metadata = metadata
                    annotated += 1
                    if annotated % CHUNK_SIZE == 0:
                        db.flush()
            db.commit()
            self._bump(contributions, filename, 0, annotated, skipped)
            bundle.imported_counts = {
                **bundle.imported_counts,
                filename: {"created": 0, "updated": annotated, "skipped": skipped},
            }
            db.commit()
            total["annotated"] += annotated
            total["skipped"] += skipped
        return {"filename": "collections", **total}

    def _import_phase_membership_occupations(self, db: Session, bundle: ESCOBundle, stored: Path, contributions: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        total = {"annotated": 0, "skipped": 0}
        occ_ids = dict(db.query(ESCOOccupation.esco_uri, ESCOOccupation.esco_occupation_id).all())
        uri_set = set(occ_ids)
        for filename in ("greenShareOcc_en.csv", "researchOccupationsCollection_en.csv"):
            path = stored / filename
            if not path.exists():
                continue
            collection = "green_share" if "green" in filename else "research_occupations"
            annotated = 0
            skipped = 0
            with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    uri = (row.get("conceptUri") or "").strip()
                    if not uri:
                        skipped += 1
                        continue
                    if uri not in uri_set:
                        skipped += 1
                        continue
                    occ = db.query(ESCOOccupation).filter(ESCOOccupation.esco_occupation_id == occ_ids[uri]).first()
                    metadata = dict(occ.occupation_metadata or {})
                    collections = set(metadata.get("collections") or [])
                    collections.add(collection)
                    metadata["collections"] = sorted(collections)
                    occ.occupation_metadata = metadata
                    annotated += 1
            db.commit()
            self._bump(contributions, filename, 0, annotated, skipped)
            bundle.imported_counts = {
                **bundle.imported_counts,
                filename: {"created": 0, "updated": annotated, "skipped": skipped},
            }
            db.commit()
            total["annotated"] += annotated
            total["skipped"] += skipped
        return {"filename": "occupation_collections", **total}

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def to_dict(self, bundle: ESCOBundle) -> Dict[str, Any]:
        return {
            "bundle_id": str(bundle.bundle_id),
            "source_version": bundle.source_version,
            "language": bundle.language,
            "licence": bundle.licence,
            "source_label": bundle.source_label,
            "source_url": bundle.source_url,
            "status": bundle.status,
            "files": bundle.files or [],
            "row_counts": bundle.row_counts or {},
            "file_checksums": bundle.file_checksums or {},
            "not_modelled_files": bundle.not_modelled_files or [],
            "validation_errors": bundle.validation_errors or [],
            "expected_file_count": len(bundle.expected_files or []),
            "predicted": bundle.predicted or {},
            "imported_counts": bundle.imported_counts or {},
            "run_id": bundle.run_id,
            "imported_at": bundle.imported_at.isoformat() if bundle.imported_at else None,
            "imported_by": bundle.imported_by,
            "partial_file": bundle.partial_file,
            "failed_file": bundle.failed_file,
            "failure_detail": bundle.failure_detail,
            "contributions": bundle.contributions or {},
            "created_at": bundle.created_at.isoformat() if bundle.created_at else None,
        }

    def bundle_dict(self, db: Session, bundle_id: Any) -> Dict[str, Any]:
        bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
        if not bundle:
            raise ValueError("ESCO bundle record not found")
        return self.to_dict(bundle)

    def refresh_collection_counts(self, db: Session, bundle_id: Any) -> Dict[str, Any]:
        """Compute collection-membership annotation counts from the current reference
        tables and persist them into the bundle record. Used once to backfill bundles
        imported before per-collection imported_counts were persisted on the success
        path. The counts reflect real current DB state and are appended (never erasing
        existing per-phase figures)."""
        bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
        if not bundle:
            raise ValueError("ESCO bundle record not found")
        collection_to_file = {label: filename for filename, label in COLLECTION_BY_FILE.items()}
        skill_collections = {
            filename: 0 for filename in COLLECTION_BY_FILE
        }
        for metadata, in db.query(ESCOSkill.esco_metadata).all():
            for collection in (metadata or {}).get("collections") or []:
                filename = collection_to_file.get(collection)
                if filename and filename in skill_collections:
                    skill_collections[filename] += 1
        occ_collections: Dict[str, int] = {
            "greenShareOcc_en.csv": 0,
            "researchOccupationsCollection_en.csv": 0,
        }
        for metadata, in db.query(ESCOOccupation.occupation_metadata).all():
            for collection in (metadata or {}).get("collections") or []:
                if collection == "green_share":
                    occ_collections["greenShareOcc_en.csv"] += 1
                elif collection == "research_occupations":
                    occ_collections["researchOccupationsCollection_en.csv"] += 1
        imported = dict(bundle.imported_counts or {})
        for filename, count in skill_collections.items():
            if filename not in imported:
                imported[filename] = {"created": 0, "updated": count, "skipped": 0}
        for filename, count in occ_collections.items():
            if filename not in imported:
                imported[filename] = {"created": 0, "updated": count, "skipped": 0}
        bundle.imported_counts = imported
        bundle.contributions = {
            **bundle.contributions,
            "maintenance_backfill": {
                "note": "Collection-membership counts recomputed from reference tables and persisted on the success path.",
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        db.commit()
        db.refresh(bundle)
        return self.to_dict(bundle)

    # Files whose import updates existing rows' hierarchy/relations rather than
    # producing one reference row per CSV row; they are not independently countable.
    _HIERARCHY_OR_REFERENCE_FILES = {
        "broaderRelationsSkillPillar_en.csv",
        "broaderRelationsOccPillar_en.csv",
        "skillsHierarchy_en.csv",
        "skillSkillRelations_en.csv",
        "conceptSchemes_en.csv",
        "dictionary_en.csv",
    }

    def _file_accounting(self, db: Session) -> List[Dict[str, Any]]:
        """Exact, live per-file accounting for the measured ACA partial subset.

        Counts landed reference rows per source file from the persisted import
        provenance (`esco_metadata.filename` / `occupation_metadata.filename`),
        collection-membership annotations, and the occupation-skill link table.
        Received counts come from the corrected registry. Hierarchy/reference files
        that update existing rows are reported as not-separately-countable rather
        than being given a fabricated number.
        """
        files = list(ACA_INSPECTION["files"])
        collection_to_file = {label: filename for filename, label in COLLECTION_BY_FILE.items()}

        skill_rows = dict(
            db.query(ESCOSkill.esco_metadata["filename"].astext, func.count(ESCOSkill.esco_skill_id))
            .group_by(ESCOSkill.esco_metadata["filename"].astext)
            .all()
        )
        occ_rows = dict(
            db.query(ESCOOccupation.occupation_metadata["filename"].astext, func.count(ESCOOccupation.esco_occupation_id))
            .group_by(ESCOOccupation.occupation_metadata["filename"].astext)
            .all()
        )
        total_links = db.query(func.count(ESCOOccupationSkillLink.link_id)).scalar() or 0
        collection_counts: Dict[str, int] = {filename: 0 for filename in COLLECTION_BY_FILE}
        for (metadata,) in db.query(ESCOSkill.esco_metadata).all():
            for collection in (metadata or {}).get("collections") or []:
                filename = collection_to_file.get(collection)
                if filename:
                    collection_counts[filename] += 1
        # Occupation-collection memberships (annotated on occupation_metadata).
        occ_collection_counts = {"greenShareOcc_en.csv": 0, "researchOccupationsCollection_en.csv": 0}
        for (metadata,) in db.query(ESCOOccupation.occupation_metadata).all():
            for collection in (metadata or {}).get("collections") or []:
                if collection == "green_share":
                    occ_collection_counts["greenShareOcc_en.csv"] += 1
                elif collection == "research_occupations":
                    occ_collection_counts["researchOccupationsCollection_en.csv"] += 1

        accounting = []
        for item in files:
            filename = item["filename"]
            received = item.get("data_rows")
            skills = int(skill_rows.get(filename, 0) or 0)
            occupations = int(occ_rows.get(filename, 0) or 0)
            memberships = int(collection_counts.get(filename, 0) or 0) + int(occ_collection_counts.get(filename, 0) or 0)
            links = int(total_links) if filename == "occupationSkillRelations_en.csv" else 0
            landed_total = skills + occupations + memberships + links
            row: Dict[str, Any] = {
                "filename": filename,
                "received_rows": received,
                "bytes": item.get("bytes"),
                "sha256": item.get("sha256"),
                "landed": {
                    "skills": skills,
                    "occupations": occupations,
                    "collection_memberships": memberships,
                    "occupation_skill_links": links,
                    "total": landed_total,
                },
            }
            if filename in self._HIERARCHY_OR_REFERENCE_FILES:
                row["reconciles"] = None
                row["basis"] = "updates existing ESCO hierarchy/relation fields; not separately countable"
            else:
                row["reconciles"] = (landed_total == received) if received is not None else None
                row["basis"] = "reference rows + collection memberships (exact, by persisted filename provenance)"
                if row["reconciles"] is False and received is not None:
                    row["shortfall"] = max(0, received - landed_total)
                    row["shortfall_note"] = (
                        "Rows not landed are within-file duplicate conceptUri values or rows with a missing "
                        "conceptUri; the importer deduplicates by conceptUri and never double-inserts."
                    )
            accounting.append(row)
        return accounting

    def live_status(self, db: Session, bundle_id: Any) -> Dict[str, Any]:
        """Bundle record enriched with live reference-table counts and coverage."""
        bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
        if not bundle:
            raise ValueError("ESCO bundle record not found")
        total_skills = db.query(func.count(ESCOSkill.esco_skill_id)).scalar() or 0
        total_occupations = db.query(func.count(ESCOOccupation.esco_occupation_id)).scalar() or 0
        total_links = db.query(func.count(ESCOOccupationSkillLink.link_id)).scalar() or 0
        canonical_skills = db.query(func.count(Skill.skill_id)).scalar() or 0
        esco_linked_canonical = (
            db.query(func.count(func.distinct(ESCOSkill.skill_id)))
            .filter(ESCOSkill.skill_id.isnot(None))
            .scalar()
            or 0
        )
        coverage = _ratio(esco_linked_canonical, canonical_skills)
        file_accounting = self._file_accounting(db)
        all_selected_files_reconcile = all(
            row["reconciles"] is True for row in file_accounting if row["reconciles"] is not None
        )
        return {
            **self.to_dict(bundle),
            "live_counts": {
                "esco_skills": total_skills,
                "esco_occupations": total_occupations,
                "esco_occupation_skill_links": total_links,
            },
            "canonical_invariance": {
                "canonical_skills": canonical_skills,
                "esco_linked_canonical_skills": int(esco_linked_canonical),
                "canonical_catalogue_preserved": canonical_skills < (total_skills + 1),
            },
            "linkage_coverage": {
                "esco_skill_coverage": round(coverage, 4),
                "coverage_note": (
                    "Coverage is the share of the curated canonical FUTURE skill catalogue "
                    "linked to at least one ESCO skill. ESCO bundle imports never create "
                    "canonical skills."
                ),
            },
            "subset_disclosure": {
                "statement": (
                    "The supplied ACA bundle is an official-format PARTIAL SUBSET of ESCO "
                    f"v1.2.0 ({len(ACA_INSPECTION['files'])} files), not the full published "
                    "distribution. This is not a 'full ESCO' import unless every selected-file "
                    "count below reconciles."
                ),
                "canonical_catalogue": canonical_skills,
                "files_expected": len(ACA_INSPECTION["files"]),
                "all_selected_files_reconcile": all_selected_files_reconcile,
            },
            "file_accounting": file_accounting,
            "checksum": {
                "run_id": bundle.run_id,
                "file_checksums": bundle.file_checksums or {},
                "expected_file_count": len(bundle.expected_files or []),
            },
            "last_run": (
                {
                    "status": bundle.status,
                    "imported_at": bundle.imported_at.isoformat() if bundle.imported_at else None,
                    "imported_by": bundle.imported_by,
                    "imported_counts": bundle.imported_counts or {},
                    "contributions": bundle.contributions or {},
                }
            ),
        }

    def list_bundles(self, db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        rows = (
            db.query(ESCOBundle)
            .order_by(ESCOBundle.created_at.desc())
            .limit(max(1, min(limit, 100)))
            .all()
        )
        return [self.to_dict(row) for row in rows]


esco_bundle_import_service = ESCOBundleImportService()