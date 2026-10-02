#!/usr/bin/env python3
"""Register the public and uploaded evidence supporting the CPUT ADICTA pilot."""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_governance_evidence import CurriculumGovernanceEvidence
from app.models.curriculum_subject_profile import CurriculumSubjectProfile


def upsert(db, *, key, **values):
    item = db.query(CurriculumGovernanceEvidence).filter(
        CurriculumGovernanceEvidence.evidence_key == key
    ).first()
    action = "UPDATE" if item else "CREATE"
    if not item:
        item = CurriculumGovernanceEvidence(evidence_key=key)
        db.add(item)
    for field, value in values.items():
        setattr(item, field, value)
    db.flush()
    print(f"{action} {key}")
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        programme = db.query(AcademicProgramme).filter(
            AcademicProgramme.programme_key == "ADICTA"
        ).first()
        if not programme:
            raise SystemExit("Programme ADICTA was not found")
        profiles = db.query(CurriculumSubjectProfile).filter(
            CurriculumSubjectProfile.programme_id == programme.programme_id,
            CurriculumSubjectProfile.validation_status == "validated",
        ).all()
        latest = {}
        for profile in profiles:
            latest.setdefault(profile.subject_code, profile)
        profiles = list(latest.values())
        codes = sorted(profile.subject_code for profile in profiles)
        credit_total = sum(profile.credits or 0 for profile in profiles)
        if len(codes) != 5 or credit_total != 120:
            raise SystemExit(f"Expected five validated modules and 120 credits; found {codes} / {credit_total}")

        saqa = upsert(
            db, key="public:saqa:104714", programme_id=programme.programme_id,
            layer="saqa_registration", authority="SAQA",
            title="Advanced Diploma in Information and Communication Technology in Applications Development",
            identifier="104714 / EXCO 0427/24", version_label="Reregistered",
            official_url="https://regqs.saqa.org.za/viewQualification.php?id=104714",
            effective_from=date(2024, 10, 3), effective_to=date(2027, 6, 30),
            currency_status="current", verification_status="verified", nqf_level=7, credits=120,
            notes="Public SAQA record; CHE is listed as quality-assurance functionary.",
            evidence_metadata={"evidence_class": "public_official", "retrieval_date": "2026-09-06",
                "empirical_use_permitted": True, "programme_code": "ADICTA"},
        )
        prospectus = upsert(
            db, key="public:cput:prospectus:220:adicta", programme_id=programme.programme_id,
            parent_evidence_id=saqa.evidence_id, layer="institutional_programme", authority="CPUT",
            title="CPUT online prospectus — ADICTA Applications Development", identifier="220 / ADICTA",
            official_url="https://prospectus.cput.ac.za/index.php/course-details?f=220&q=ADICTA",
            currency_status="current", verification_status="verified", nqf_level=7, credits=120,
            notes="Public institutional prospectus. This is not a Senate approval record.",
            evidence_metadata={"evidence_class": "public_official", "retrieval_date": "2026-09-06",
                "empirical_use_permitted": True, "programme_code": "ADICTA"},
        )
        upsert(
            db, key="uploaded:cput:adicta:validated-subject-guides:2022",
            programme_id=programme.programme_id, parent_evidence_id=prospectus.evidence_id,
            layer="module_curriculum", authority="CPUT",
            title="Validated CPUT ADICTA subject-guide corpus (five canonical modules)",
            identifier="ADP470S, ADT470S, PFD470S, PRJ470S, REM475S", version_label="2022 subject guides",
            currency_status="historical", verification_status="verified", nqf_level=7, credits=120,
            notes="Uploaded source files and extracted chunks are retained in the evidence store.",
            evidence_metadata={"evidence_class": "authorised_uploaded_curriculum",
                "empirical_use_permitted": True, "programme_code": "ADICTA",
                "module_codes": codes, "credit_total": credit_total},
        )
        if args.apply:
            db.commit()
            print("Applied public/uploaded ADICTA governance evidence")
        else:
            db.rollback()
            print("Preview only; rerun with --apply to commit")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
