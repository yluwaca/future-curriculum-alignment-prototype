#!/usr/bin/env python3
"""Seed clearly labelled, replaceable governance records for technical UAT only."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_governance_evidence import CurriculumGovernanceEvidence

LAYERS = (
    ("che_accreditation", "CHE", "Synthetic CHE accreditation placeholder"),
    ("dhet_pqm", "DHET", "Synthetic DHET PQM approval placeholder"),
    ("institutional_programme", "CPUT", "Synthetic institutional approval placeholder"),
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--programme-code", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    code = args.programme_code.upper().strip()
    db = SessionLocal()
    try:
        programme = db.query(AcademicProgramme).filter(AcademicProgramme.programme_key == code).first()
        if not programme:
            raise SystemExit(f"Programme {code} was not found")
        changed = 0
        for layer, authority, title in LAYERS:
            key = f"synthetic-uat:{code.lower()}:{layer}"
            item = db.query(CurriculumGovernanceEvidence).filter(CurriculumGovernanceEvidence.evidence_key == key).first()
            if item:
                print(f"KEEP {key}")
                continue
            db.add(CurriculumGovernanceEvidence(
                programme_id=programme.programme_id, layer=layer, authority=authority,
                evidence_key=key, title=f"SYNTHETIC UAT — NOT EMPIRICAL EVIDENCE — {title}",
                identifier=f"SYNTHETIC-{code}-{layer.upper()}", currency_status="current",
                verification_status="verified",
                notes="Technical test fixture only. Replace with the official institution-specific record after ethics and data-sharing approval; never cite as a regulatory fact.",
                evidence_metadata={"evidence_class": "synthetic_uat", "empirical_use_permitted": False,
                    "replacement_required": True, "replacement_match": {"programme_code": code,
                    "layer": layer, "required_fields": ["official reference", "source document", "effective date"]}},
            ))
            print(f"CREATE {key}")
            changed += 1
        if args.apply:
            db.commit()
            print(f"Applied {changed} synthetic UAT governance record(s)")
        else:
            db.rollback()
            print("Preview only; rerun with --apply to commit")
        return 0
    finally:
        db.close()

if __name__ == "__main__":
    raise SystemExit(main())
