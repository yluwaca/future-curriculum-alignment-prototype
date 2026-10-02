#!/usr/bin/env python
"""Seed a deterministic, development-only locked alignment-label snapshot.

This utility exists only to exercise the chronological training pipeline in DEV/UAT.
Synthetic rows and any metrics derived from them MUST NOT be reported as empirical
research findings or promoted as a production model candidate.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.session import SessionLocal  # noqa: E402
from app.models.label_dataset_snapshot import LabelDatasetSnapshot, LabelDatasetSnapshotRow  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.label_dataset_snapshot_service import label_dataset_snapshot_service  # noqa: E402
from app.services.reviewed_alignment_training_dataset_service import reviewed_alignment_training_dataset_service  # noqa: E402

NAMESPACE = uuid.UUID("e46ffebd-fd3e-4b67-93bb-8fb9d66251da")


def stable_uuid(kind: str, index: int) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"future-synthetic-reviewed-v1:{kind}:{index}")


def build_rows(count: int) -> list[dict]:
    labels = [1, 4, 2, 5, 3, 4]
    base = datetime(2022, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        final_label = labels[index % len(labels)]
        window_end = base + timedelta(days=30 * index)
        task_id = stable_uuid("task", index)
        document_id = stable_uuid("document", index // 4)
        version_id = stable_uuid("version", index // 4)
        evidence_window_hash = label_dataset_snapshot_service.fingerprint(
            {"synthetic_window": index, "window_end": window_end.isoformat()}
        )
        rows.append({
            "task_id": str(task_id),
            "document_id": str(document_id),
            "version_id": str(version_id),
            "chunk_id": None,
            "evidence_window_hash": evidence_window_hash,
            "curriculum_evidence": (
                f"SYNTHETIC DEV evidence row {index}: curriculum skill coverage "
                f"and learning outcomes for alignment class {final_label}."
            ),
            "labour_market_evidence": [{
                "signal": f"synthetic-demand-{index % 7}",
                "demand_score": round(0.15 + (index % 9) * 0.09, 3),
                "confidence": round(0.55 + (index % 5) * 0.08, 3),
                "period_end": window_end.isoformat(),
            }],
            "evidence_metadata": {
                "window_end": window_end.isoformat(),
                "synthetic": True,
                "development_only": True,
                "source": "scripts/seed_locked_reviewed_dataset.py",
            },
            "final_alignment_label": final_label,
            "labels": [
                {
                    "label_id": str(stable_uuid("label-first", index)),
                    "review_stage": "first",
                    "alignment_label": final_label,
                    "confidence": 4,
                    "justification": "Synthetic development-only label.",
                    "present_skills": [f"synthetic-skill-{index % 6}"],
                    "missing_skills": [f"synthetic-gap-{index % 4}"],
                    "reviewer_id": "synthetic-reviewer-a",
                },
                {
                    "label_id": str(stable_uuid("label-second", index)),
                    "review_stage": "second",
                    "alignment_label": final_label,
                    "confidence": 4,
                    "justification": "Synthetic development-only confirmation.",
                    "present_skills": [f"synthetic-skill-{index % 6}"],
                    "missing_skills": [f"synthetic-gap-{index % 4}"],
                    "reviewer_id": "synthetic-reviewer-b",
                },
            ],
        })
    return rows


def seed(actor_id: str, count: int, dry_run: bool) -> LabelDatasetSnapshot:
    if count < 20:
        raise ValueError("--rows must be at least 20")
    db = SessionLocal()
    try:
        actor = db.query(User).filter(User.identity_id == actor_id, User.is_active.is_(True)).first()
        if actor is None:
            raise ValueError(f"Active system identity {actor_id!r} was not found")

        row_payloads = build_rows(count)
        rules = {**label_dataset_snapshot_service.inclusion_rules(), "synthetic_seed": True}
        fingerprint = label_dataset_snapshot_service.fingerprint({
            "schema": label_dataset_snapshot_service.FEATURE_SCHEMA,
            "rubric": label_dataset_snapshot_service.RUBRIC,
            "inclusion_rules": rules,
            "rows": row_payloads,
        })
        existing = db.query(LabelDatasetSnapshot).filter(
            LabelDatasetSnapshot.dataset_fingerprint == fingerprint
        ).first()
        if existing:
            print(f"Identical snapshot already exists: {existing.snapshot_id}")
            return existing

        now = datetime.now(timezone.utc)
        distribution = Counter(str(row["final_alignment_label"]) for row in row_payloads)
        snapshot = LabelDatasetSnapshot(
            snapshot_version=f"synthetic_dev_alignment_labels_{now.strftime('%Y%m%d_%H%M%S_%f')}",
            dataset_fingerprint=fingerprint,
            lifecycle_state="approved_locked",
            row_count=count,
            locked_at=now,
            locked_by=actor_id,
            label_rubric=label_dataset_snapshot_service.RUBRIC,
            inclusion_rules=rules,
            exclusion_summary={},
            feature_schema=label_dataset_snapshot_service.FEATURE_SCHEMA,
            manifest={
                "row_count": count,
                "label_distribution": dict(distribution),
                "task_ids": [row["task_id"] for row in row_payloads],
                "source_version_ids": sorted({row["version_id"] for row in row_payloads}),
                "evidence_window_hashes": [row["evidence_window_hash"] for row in row_payloads],
                "synthetic": True,
                "development_only": True,
            },
            dataset_card={
                "name": "FUTURE synthetic reviewed alignment labels (DEV ONLY)",
                "purpose": "Technical validation of locking, TimeSeriesSplit, and model-registry plumbing",
                "unit_of_analysis": "synthetic curriculum/labour evidence pair",
                "label_provenance": "programmatically generated; not expert reviewed",
                "limitations": [
                    "Contains no empirical observations.",
                    "Metrics derived from this snapshot are not research results.",
                    "Must not be promoted as a production or journal-reportable candidate.",
                ],
                "ethical_use": "Development and UAT pipeline testing only.",
                "synthetic": True,
            },
            notes="SYNTHETIC DEVELOPMENT-ONLY DATASET. Not valid for empirical claims.",
        )
        db.add(snapshot)
        db.flush()
        for index, payload in enumerate(row_payloads):
            labels = payload["labels"]
            db.add(LabelDatasetSnapshotRow(
                snapshot_id=snapshot.snapshot_id,
                row_index=index,
                task_id=uuid.UUID(payload["task_id"]),
                document_id=uuid.UUID(payload["document_id"]),
                version_id=uuid.UUID(payload["version_id"]),
                chunk_id=None,
                evidence_window_hash=payload["evidence_window_hash"],
                curriculum_evidence_hash=label_dataset_snapshot_service.fingerprint(payload["curriculum_evidence"]),
                final_alignment_label=payload["final_alignment_label"],
                label_ids=[label["label_id"] for label in labels],
                reviewer_ids=[label["reviewer_id"] for label in labels],
                row_payload=payload,
                row_fingerprint=label_dataset_snapshot_service.fingerprint(payload),
            ))
        db.flush()
        loaded = reviewed_alignment_training_dataset_service.load(db, snapshot)
        if loaded["row_count"] != count:
            raise RuntimeError(f"Validation loaded {loaded['row_count']} rows; expected {count}")
        print(f"Validated snapshot {snapshot.snapshot_id}: {count} rows, labels={dict(distribution)}")
        if dry_run:
            db.rollback()
            print("Dry run complete; transaction rolled back.")
        else:
            db.commit()
            print("Committed development-only snapshot.")
        return snapshot
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True, help="Existing active jus01_systemidentity.identity_id")
    parser.add_argument("--rows", type=int, default=24, help="Synthetic rows (minimum 20; default 24)")
    parser.add_argument("--dry-run", action="store_true", help="Validate in a transaction and roll it back")
    args = parser.parse_args()
    seed(args.actor_id, args.rows, args.dry_run)


if __name__ == "__main__":
    main()
