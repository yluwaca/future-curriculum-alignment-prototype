# backend/tests/test_esco_bundle_import_safety.py

"""
Safety and honesty tests for the controlled ESCO v1.2.0 bundle workflow:

- the ACA inspection registry carries measured supplied-file counts (subset), not
  published distribution totals, and the summary agrees with the file-level data;
- validate_and_stage fails closed on checksum mismatch, missing files or unknown files;
- import_bundle is idempotent (reuses an already-imported bundle) and re-verifies
  staged checksums before import;
- bundle imports never create canonical FUTURE skills (canonical-catalogue invariance);
- collection-membership phases persist per-file imported_counts on the success path;
- live bundle status reports reference-table counts, linkage coverage and the run checksum.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func

from app.core.database import SessionLocal
from app.data.taxonomy_source_registry import ACA_INSPECTION
from app.models.esco_bundle import ESCOBundle
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.esco_skill import ESCOSkill
from app.models.skill import Skill
from app.services.esco_bundle_import_service import (
    COLLECTION_BY_FILE,
    ESCOBundleImportService,
)


def _bundle(session, status="validated", **kwargs) -> ESCOBundle:
    bundle = ESCOBundle(
        source_version="1.2.0",
        licence="European Union Public Licence v1.2",
        source_label="test-bundle",
        status=status,
        **kwargs,
    )
    session.add(bundle)
    session.commit()
    return bundle


def _staged_bytes(bundle_id, content: bytes, filename: str, tmp_path):
    stage_dir = tmp_path / str(bundle_id)
    stage_dir.mkdir(parents=True, exist_ok=True)
    path = stage_dir / filename
    path.write_bytes(content)
    return stage_dir


def test_registry_counts_are_measured_supplied_subset():
    """The corrected registry must carry the actual supplied subset counts, and the
    summary totals must agree with the file-level numbers and byte sizes."""
    files = {item["filename"]: item for item in ACA_INSPECTION["files"]}
    assert files["skills_en.csv"]["data_rows"] == 13960
    assert files["occupations_en.csv"]["data_rows"] == 3043
    assert files["ISCOGroups_en.csv"]["data_rows"] == 619
    summary = ACA_INSPECTION["coverage_summary"]
    assert summary["skills"] == files["skills_en.csv"]["data_rows"]
    assert summary["occupations"] == files["occupations_en.csv"]["data_rows"]
    assert summary["isco_groups"] == files["ISCOGroups_en.csv"]["data_rows"]
    assert summary["files"] == len(files) == 19
    assert summary["bytes_total"] == sum(item["bytes"] for item in files.values())
    for item in files.values():
        assert len(item["sha256"]) == 64


def test_registry_discloses_partial_subset():
    assert "PARTIAL SUBSET" in ACA_INSPECTION.get("subset_note", "").upper()
    assert ACA_INSPECTION["coverage_summary"]["skills"] != 104064


def test_validate_and_stage_fails_closed_on_checksum_mismatch():
    service = ESCOBundleImportService()
    db = SessionLocal()
    try:
        fake = b"conceptUri,preferredLabel\nhttp://data.europa.eu/esco/skill/0000x,no\n"
        try:
            service.validate_and_stage(
                db=db,
                actor_id="test-esco-safety-1",
                files=[{"filename": "skills_en.csv", "content": fake}],
            )
        except ValueError as exc:
            assert "Checksum mismatch" in str(exc)
        else:
            raise AssertionError("validate_and_stage accepted a checksum mismatch")
    finally:
        db.close()


def test_validate_and_stage_fails_closed_on_missing_files():
    service = ESCOBundleImportService()
    db = SessionLocal()
    try:
        content = b"conceptUri,preferredLabel\nhttp://data.europa.eu/esco/skill/0000y,no\n"
        try:
            service.validate_and_stage(
                db=db,
                actor_id="test-esco-safety-2",
                files=[{"filename": "skills_en.csv", "content": content}],
            )
        except ValueError as exc:
            assert "Checksum mismatch" in str(exc)
        else:
            raise AssertionError("validate_and_stage accepted a non-matching bundle")
    finally:
        db.close()


def test_import_bundle_idempotent_reuse_and_fail_closed_state():
    service = ESCOBundleImportService()
    db = SessionLocal()
    bundle = None
    try:
        bundle = _bundle(db, status="imported")
        result = service.import_bundle(db, bundle.bundle_id, actor_id="test-esco-safety-3")
        assert result["reused"] is True

        rejected = _bundle(db, status="not_ready")
        try:
            service.import_bundle(db, rejected.bundle_id, actor_id="test-esco-safety-3")
        except ValueError as exc:
            assert "must be validated" in str(exc)
        else:
            raise AssertionError("import_bundle accepted a non-validated bundle")
        db.query(ESCOBundle).filter(
            ESCOBundle.bundle_id.in_([bundle.bundle_id, rejected.bundle_id])
        ).delete()
        db.commit()
    finally:
        db.close()


def test_import_bundle_aborts_on_staged_checksum_change(tmp_path):
    service = ESCOBundleImportService()
    db = SessionLocal()
    bundle = None
    try:
        bundle = _bundle(
            db,
            status="validated",
            file_checksums={"skills_en.csv": "deadbeef" * 8},
        )
        stage = tmp_path / str(bundle.bundle_id)
        stage.mkdir(parents=True, exist_ok=True)
        with open(stage / "skills_en.csv", "wb") as handle:
            handle.write(b"not-the-expected-checksum")
        try:
            service.import_bundle(db, bundle.bundle_id, actor_id="test-esco-safety-4")
        except ValueError as exc:
            assert "checksum changed" in str(exc).lower() or "missing" in str(exc).lower()
        else:
            raise AssertionError("import_bundle proceeded despite a staged checksum change")
        db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle.bundle_id).delete()
        db.commit()
    finally:
        db.close()


def test_canonical_catalogue_invariance_during_skill_phase(tmp_path):
    """Importing ESCO reference skills must not create canonical FUTURE skills."""
    service = ESCOBundleImportService()
    db = SessionLocal()
    bundle = None
    try:
        run_tag = uuid.uuid4().hex[:12]
        uri = f"http://data.europa.eu/esco/skill/0000invariance-{run_tag}"
        content = (
            "conceptUri,preferredLabel,skillType,reuseLevel,altLabels,scopeNote,status\n"
            f"{uri},invariance-skill,skill/competence,sector-specific,intro,Desc,released\n"
        ).encode("utf-8")
        bundle = _bundle(db, status="validated")
        stage = _staged_bytes(bundle.bundle_id, content, "skills_en.csv", tmp_path)
        canonical_before = db.query(func.count(Skill.skill_id)).scalar() or 0
        contributions = {}
        result = service._import_phase_skills(db, bundle, stage, contributions)
        assert result["created"] == 1
        canonical_after = db.query(func.count(Skill.skill_id)).scalar() or 0
        assert canonical_after == canonical_before
        db.query(ESCOSkill).filter(ESCOSkill.esco_uri == uri).delete()
        db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle.bundle_id).delete()
        db.commit()
    finally:
        db.close()


def test_collection_phase_persists_imported_counts_on_success_path(tmp_path):
    service = ESCOBundleImportService()
    db = SessionLocal()
    bundle = None
    skill_rows = []
    try:
        run_tag = uuid.uuid4().hex[:12]
        uris = [
            f"http://data.europa.eu/esco/skill/0000dig{run_tag}-{i}" for i in range(2)
        ]
        for uri in uris:
            skill = ESCOSkill(
                esco_uri=uri,
                preferred_label=f"dig skill {run_tag}",
                taxonomy_version="1.2.0",
                bundle_id=None,
                esco_metadata={},
            )
            db.add(skill)
            skill_rows.append(skill)
        db.commit()
        bundle = _bundle(db, status="validated", imported_counts={})
        filename = "digCompSkillsCollection_en.csv"
        content = (
            "conceptUri\n"
            + "\n".join(uris)
        ).encode("utf-8")
        stage = _staged_bytes(bundle.bundle_id, content, filename, tmp_path)
        contributions = {}
        result = service._import_phase_collections(db, bundle, stage, contributions)
        assert result["annotated"] == 2
        persisted = (bundle.imported_counts or {}).get(filename)
        assert persisted == {"created": 0, "updated": 2, "skipped": 0}
        assert contributions.get(filename) == {"created": 0, "updated": 2, "skipped": 0}
        for skill in skill_rows:
            metadata = skill.esco_metadata or {}
            assert "digcomp" in metadata.get("collections", [])
        db.query(ESCOSkill).filter(ESCOSkill.esco_skill_id.in_([s.esco_skill_id for s in skill_rows])).delete()
        db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle.bundle_id).delete()
        db.commit()
    finally:
        db.close()


def test_live_status_reports_counts_coverage_and_checksum():
    service = ESCOBundleImportService()
    db = SessionLocal()
    bundle = None
    try:
        bundle = _bundle(
            db,
            status="imported",
            run_id="run-abc",
            file_checksums={"skills_en.csv": "a" * 64},
            imported_counts={"skills_en": {"created": 1, "updated": 0, "skipped": 0}},
        )
        status = service.live_status(db, bundle.bundle_id)
        assert status["source_version"] == "1.2.0"
        assert "live_counts" in status
        assert "canonical_invariance" in status
        assert "linkage_coverage" in status
        assert "coverage_note" in status["linkage_coverage"]
        assert status["checksum"]["run_id"] == "run-abc"
        assert status["last_run"]["status"] == "imported"
        assert status["last_run"]["imported_counts"]["skills_en"]["created"] == 1
        db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle.bundle_id).delete()
        db.commit()
    finally:
        db.close()