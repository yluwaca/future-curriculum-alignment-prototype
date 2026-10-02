# backend/tests/test_esco_bundle_preview_bytes.py

"""
Regression coverage for the ESCO bundle upload path that operates on in-memory
bytes (FastAPI UploadFile content). Live acceptance exposed a bug where the
preview handler passed io.BytesIO into helper functions that only accepted a
filesystem Path, producing a 500 even though the multipart upload got through
nginx. These tests pin the bytes-first contract for the read-only preview and
predicted-count helpers.
"""

import io

from sqlalchemy import func

from app.core.database import SessionLocal
from app.services.esco_bundle_import_service import (
    ESCOBundleImportService,
    _count_rows,
)


def _skill_rows() -> bytes:
    header = "conceptUri,conceptType,code,preferredLabel,altLabels,hiddenLabels,status,modifiedDate,scopeNote,definition,description,dctType\n"
    row = (
        "http://data.europa.eu/esco/skill/0001,TEST_SKILL,0001,Regress skill,,,released,2024-01-01,,Test definition against preview,,skill\n"
        "http://data.europa.eu/esco/skill/0002,TEST_SKILL,0002,Regress skill two,,,released,2024-01-01,,Test definition two,,skill\n"
    )
    return (header + row).encode("utf-8")


def test_count_rows_accepts_bytesio():
    payload = b"header\nrow1\nrow2\nrow3\n"
    assert _count_rows(io.BytesIO(payload)) == 3


def test_count_rows_accepts_utf8_bom():
    payload = "\ufeffheader\nrow1\n".encode("utf-8-sig")
    assert _count_rows(io.BytesIO(payload)) == 1


def test_count_rows_returns_zero_for_empty():
    assert _count_rows(io.BytesIO(b"")) == 0


def test_count_rows_accepts_path(tmp_path):
    p = tmp_path / "rows.csv"
    p.write_text("col\n1\n2\n", encoding="utf-8")
    assert _count_rows(p) == 2


def test_preview_files_accepts_bytes_uploads():
    content = _skill_rows()
    result = ESCOBundleImportService().preview_files([{"filename": "skills_en.csv", "content": content}])
    assert result["file_count"] == 1
    assert result["totals"]["rows"] == 2
    assert result["totals"]["bytes"] == len(content)
    assert "occupations_en.csv" in result["missing"]
    entry = result["files"][0]
    assert entry["detected_type"] == "esco_skill"
    assert entry["data_rows"] == 2
    assert entry["validated"] is True
    assert result["validation_failures"] == []


def test_service_preview_files_uses_row_counts_without_disk():
    service = ESCOBundleImportService()
    content = _skill_rows()
    result = service.preview_files([{"filename": "skills_en.csv", "content": content}])
    assert result["predicted"]["inserts"] == 2
    assert result["totals"]["rows"] == 2


def test_import_phase_skills_resolves_duplicate_uris_within_file(tmp_path):
    """Official ESCO v1.2.0 skills_en.csv contains duplicate conceptUri rows
    (21 duplicates among 13960 rows). The phase must upsert idempotently instead
    of violating uq_esco_skill_esco_uri during the batched flush."""
    service = ESCOBundleImportService()
    db = SessionLocal()
    try:
        import uuid

        stage_dir = tmp_path / "bundle"
        stage_dir.mkdir()
        run_tag = uuid.uuid4().hex[:12]
        dup_uri = f"http://data.europa.eu/esco/skill/0000test-{run_tag}-dup"
        other_uri = f"http://data.europa.eu/esco/skill/0000test-{run_tag}-other"
        file_path = stage_dir / "skills_en.csv"
        header = "conceptUri,preferredLabel,skillType,reuseLevel,altLabels,scopeNote,status\n"
        rows = header + (
            f"{dup_uri},duplicate-skill,skill/competence,sector-specific,intro,First occurrence,released\n"
            f"{dup_uri},duplicate-skill,skill/competence,sector-specific,intro,Second occurrence,released\n"
            f"{other_uri},other-skill,skill/competence,sector-specific,intro,Other,released\n"
        )
        file_path.write_text(rows, encoding="utf-8")

        from app.models.esco_bundle import ESCOBundle

        before = db.query(func.count(ESCOBundle.bundle_id)).scalar() or 0
        bundle = ESCOBundle(
            source_version="1.2.0",
            licence="European Union Public Licence v1.2",
            source_label="test",
            status="validated",
        )
        db.add(bundle)
        db.commit()

        contributions = {}
        result = service._import_phase_skills(db, bundle, stage_dir, contributions)
        assert result["created"] == 2
        assert result["skipped"] == 1

        from app.models.esco_skill import ESCOSkill

        dup_rows = (
            db.query(ESCOSkill)
            .filter(ESCOSkill.esco_uri == dup_uri)
            .all()
        )
        assert len(dup_rows) == 1
        assert dup_rows[0].preferred_label == "duplicate-skill"
        db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle.bundle_id).delete()
        db.commit()
    finally:
        db.close()