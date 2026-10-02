#!/usr/bin/env python3
"""Preview or apply canonical module reconciliation from validated subject profiles."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_module import CurriculumModule
from app.models.curriculum_subject_profile import CurriculumSubjectProfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--programme-code", required=True)
    parser.add_argument("--canonical-programme-code", help="Replace validated profile and programme keys")
    parser.add_argument("--credit-override", action="append", default=[], metavar="SUBJECT_CODE=CREDITS")
    parser.add_argument("--expected-total-credits", type=int)
    parser.add_argument("--apply", action="store_true", help="Commit changes; otherwise preview only")
    args = parser.parse_args()
    programme_code = args.programme_code.upper().strip()
    canonical_programme_code = (args.canonical_programme_code or programme_code).upper().strip()
    credit_overrides = {}
    for value in args.credit_override:
        try:
            subject_code, credits = value.split("=", 1)
            subject_code, credits = subject_code.upper().strip(), int(credits)
        except (TypeError, ValueError):
            raise SystemExit(f"Invalid --credit-override {value!r}; use SUBJECT_CODE=CREDITS")
        if not subject_code or credits < 0:
            raise SystemExit(f"Invalid --credit-override {value!r}; credits must be non-negative")
        credit_overrides[subject_code] = credits

    db = SessionLocal()
    try:
        profiles = db.query(CurriculumSubjectProfile).filter(CurriculumSubjectProfile.programme_code == programme_code, CurriculumSubjectProfile.validation_status == "validated").order_by(CurriculumSubjectProfile.updated_at.desc()).all()
        latest = {}
        for profile in profiles:
            latest.setdefault((profile.document_id, profile.subject_code), profile)
        profiles = list(latest.values())
        if not profiles:
            raise SystemExit(f"No validated profiles found for {programme_code}")
        canonical_codes = {profile.subject_code.upper() for profile in profiles}
        programme_ids = {profile.programme_id for profile in profiles if profile.programme_id}
        print(f"Canonical validated codes: {', '.join(sorted(canonical_codes))}")

        unknown_overrides = sorted(set(credit_overrides) - canonical_codes)
        if unknown_overrides:
            raise SystemExit("Credit overrides do not match validated subjects: " + ", ".join(unknown_overrides))
        for profile in profiles:
            subject_code = profile.subject_code.upper()
            if subject_code in credit_overrides and profile.credits != credit_overrides[subject_code]:
                print(f"UPDATE {subject_code} credits from {profile.credits} to {credit_overrides[subject_code]}")
                profile.credits = credit_overrides[subject_code]
            if profile.programme_code != canonical_programme_code:
                print(f"UPDATE {subject_code} programme code from {profile.programme_code} to {canonical_programme_code}")
                profile.programme_code = canonical_programme_code
        credit_total = sum(profile.credits or 0 for profile in profiles)
        print(f"Canonical credit total: {credit_total}")
        if args.expected_total_credits is not None and credit_total != args.expected_total_credits:
            raise SystemExit(f"Credit total {credit_total} does not match expected {args.expected_total_credits}; no changes committed")
        for profile in profiles:
            document = db.query(CurriculumDocument).filter(CurriculumDocument.document_id == profile.document_id).first()
            module = db.query(CurriculumModule).filter(CurriculumModule.module_code == profile.subject_code).first()
            if not module:
                module = CurriculumModule(module_code=profile.subject_code, module_name=profile.subject_name or profile.subject_code, programme_id=profile.programme_id, data_source="curriculum_subject_profile")
                db.add(module)
                db.flush()
                print(f"CREATE {profile.subject_code}")
            module.module_name = profile.subject_name or module.module_name
            module.programme_id = profile.programme_id or module.programme_id
            module.programme = profile.programme_name or module.programme
            module.faculty = profile.faculty or module.faculty
            module.description = profile.purpose or module.description
            module.nqf_level = profile.nqf_level
            module.credits = profile.credits
            module.is_active = True
            profile.module_id = module.module_id
            if document and profile.programme_name:
                document.programme = profile.programme_name
        aliases = []
        if programme_ids:
            aliases = db.query(CurriculumModule).filter(CurriculumModule.programme_id.in_(programme_ids), CurriculumModule.is_active.is_(True), ~CurriculumModule.module_code.in_(canonical_codes)).all()
        for module in aliases:
            module.is_active = False
            print(f"DEACTIVATE non-canonical module {module.module_code} (source={module.data_source or 'unknown'}, name={module.module_name})")
        programme_name = next((p.programme_name for p in profiles if p.programme_name), None)
        for programme_id in programme_ids:
            programme = db.query(AcademicProgramme).filter(AcademicProgramme.programme_id == programme_id).first()
            if programme and programme_name:
                if programme.programme_key != canonical_programme_code:
                    conflict = db.query(AcademicProgramme).filter(
                        AcademicProgramme.programme_key == canonical_programme_code,
                        AcademicProgramme.programme_id != programme.programme_id,
                    ).first()
                    if conflict:
                        raise SystemExit(f"Cannot rename programme key to {canonical_programme_code}: another programme already uses it")
                    print(f"RECODE programme from {programme.programme_key} to {canonical_programme_code}")
                    programme.programme_key = canonical_programme_code
                programme.name = programme_name
                programme.qualification_type = next((p.qualification_type for p in profiles if p.qualification_type), programme.qualification_type)
                programme.nqf_level = str(next((p.nqf_level for p in profiles if p.nqf_level), programme.nqf_level))
                print(f"RENAME programme to {programme_name}")
        if args.apply:
            db.commit()
            print(f"Applied: {len(profiles)} canonical module(s), {len(aliases)} alias row(s) deactivated")
        else:
            db.rollback()
            print("Preview only; rerun with --apply to commit")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
