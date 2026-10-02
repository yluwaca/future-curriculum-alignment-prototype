"""Content-addressed immutable snapshots of completed expert labels."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_expert_label import AlignmentExpertLabel
from app.models.alignment_review_task import AlignmentReviewTask
from app.models.label_dataset_snapshot import LabelDatasetSnapshot, LabelDatasetSnapshotRow


class LabelDatasetSnapshotService:
    RUBRIC = {
        "1": "No alignment",
        "2": "Weak alignment",
        "3": "Moderate alignment",
        "4": "Strong alignment",
        "5": "Very strong alignment",
    }
    FEATURE_SCHEMA = {
        "schema_name": "independent_alignment_labels_v1",
        "target": "final_alignment_label",
        "target_range": [1, 5],
        "source_identifiers": ["document_id", "version_id", "chunk_id", "evidence_window_hash"],
        "review_evidence": ["label_ids", "reviewer_ids", "justification", "present_skills", "missing_skills"],
        "model_scores_excluded": True,
    }

    def create_locked_snapshot(
        self,
        db: Session,
        actor_id: str,
        notes: str | None = None,
        dataset_mode: str = "technical_uat_researcher_operated",
    ) -> Dict[str, Any]:
        if dataset_mode not in {"technical_uat_researcher_operated", "independent_expert_validation", "rule_assisted_confirmed"}:
            raise ValueError(f"Unsupported dataset mode: {dataset_mode}")
        tasks = (
            db.query(AlignmentReviewTask)
            .filter(
                AlignmentReviewTask.status == "completed",
                AlignmentReviewTask.final_alignment_label.isnot(None),
                AlignmentReviewTask.dataset_mode == dataset_mode,
                func.coalesce(AlignmentReviewTask.evidence_metadata["excluded_from_dataset"].astext, "false") != "true",
            )
            .order_by(AlignmentReviewTask.task_id.asc())
            .all()
        )
        if not tasks:
            raise ValueError(
                f"No completed reviewed alignment tasks are available to lock for mode {dataset_mode}"
            )

        row_payloads = []
        excluded = Counter()
        for task in tasks:
            labels = (
                db.query(AlignmentExpertLabel)
                .filter(AlignmentExpertLabel.task_id == task.task_id)
                .order_by(AlignmentExpertLabel.review_stage.asc())
                .all()
            )
            stages = {label.review_stage for label in labels}
            reviewer_ids = [label.reviewer_id for label in labels]
            if dataset_mode == "rule_assisted_confirmed":
                proposal = (task.evidence_metadata or {}).get("rule_assisted_proposal") or {}
                if "first" not in stages or not proposal.get("proposal_hash") or not proposal.get("confirmed_by"):
                    excluded["missing_rule_proposal_or_confirmation"] += 1
                    continue
            else:
                if "first" not in stages or "second" not in stages:
                    excluded["missing_independent_pair"] += 1
                    continue
                if len(reviewer_ids) != len(set(reviewer_ids)):
                    excluded["reviewer_not_independent"] += 1
                    continue
            payload = {
                "task_id": str(task.task_id),
                "document_id": str(task.document_id),
                "version_id": str(task.version_id),
                "chunk_id": str(task.chunk_id) if task.chunk_id else None,
                "evidence_window_hash": task.evidence_window_hash,
                "dataset_mode": task.dataset_mode,
                "stratum": task.stratum,
                "sample_seed": task.sample_seed,
                "curriculum_evidence": task.curriculum_evidence,
                "labour_market_evidence": task.labour_market_evidence or [],
                "evidence_metadata": task.evidence_metadata or {},
                "final_alignment_label": task.final_alignment_label,
                "labels": [
                    {
                        "label_id": str(label.label_id),
                        "review_stage": label.review_stage,
                        "alignment_label": label.alignment_label,
                        "confidence": label.confidence,
                        "justification": label.justification,
                        "present_skills": label.present_skills or [],
                        "missing_skills": label.missing_skills or [],
                        "reviewer_id": label.reviewer_id,
                        "reviewer_persona": label.reviewer_persona,
                    }
                    for label in labels
                ],
            }
            row_payloads.append(payload)
        if not row_payloads:
            raise ValueError("Completed tasks failed independent-review inclusion rules")

        row_payloads.sort(key=lambda item: item["task_id"])
        fingerprint_payload = {
            "schema": self.FEATURE_SCHEMA,
            "rubric": self.RUBRIC,
            "inclusion_rules": self.inclusion_rules(dataset_mode),
            "rows": row_payloads,
        }
        fingerprint = self.fingerprint(fingerprint_payload)
        existing = db.query(LabelDatasetSnapshot).filter(
            LabelDatasetSnapshot.dataset_fingerprint == fingerprint,
            LabelDatasetSnapshot.dataset_mode == dataset_mode,
        ).first()
        if existing:
            return {**self.to_dict(existing), "reused_identical_snapshot": True}

        now = datetime.now(timezone.utc)
        distribution = Counter(str(row["final_alignment_label"]) for row in row_payloads)
        agreement_statistics = self._agreement_statistics(row_payloads)
        sample_definition = self._sample_definition(row_payloads, dataset_mode)
        manifest = {
            "row_count": len(row_payloads),
            "task_ids": [row["task_id"] for row in row_payloads],
            "source_version_ids": sorted({row["version_id"] for row in row_payloads}),
            "evidence_window_hashes": sorted({row["evidence_window_hash"] for row in row_payloads}),
            "label_distribution": dict(distribution),
        }
        if dataset_mode == "technical_uat_researcher_operated":
            dataset_card = {
                "name": "FUTURE technical UAT alignment label dataset",
                "purpose": "Operational acceptance of the alignment-review and training pipeline",
                "unit_of_analysis": "one curriculum alignment task paired with a labour-market evidence window",
                "label_provenance": (
                    "Two researcher-operated UAT analyst accounts reviewing the identical sampled tasks; "
                    "account transparency queries UQ58X are the enforced relationship. "
                    "These are NOT independent expert labels."
                ),
                "dataset_mode": "technical_uat_researcher_operated",
                "independent_expert_validation": False,
                "limitations": [
                    "Researcher-operated UAT accounts are not independent human experts; coverage of the alignment range is demonstrative only.",
                    "A separate independent_expert_validation mode must be operated before scientific claims.",
                    "Generated model scores are excluded from label construction.",
                ],
                "ethical_use": "Decision support demonstration only; do not treat UAT labels or predictions as production curriculum decisions.",
            }
        elif dataset_mode == "independent_expert_validation":
            dataset_card = {
                "name": "FUTURE independently reviewed curriculum–labour alignment labels",
                "purpose": "Supervised alignment model development and evaluation",
                "unit_of_analysis": "one curriculum alignment task paired with a labour-market evidence window",
                "label_provenance": "two independent experts; third-person adjudication on disagreement",
                "dataset_mode": "independent_expert_validation",
                "independent_expert_validation": True,
                "limitations": [
                    "Coverage is limited to validated curriculum versions and available labour-market windows.",
                    "Labels remain expert judgements and agreement must be reported.",
                    "Generated model scores are excluded from label construction.",
                ],
                "ethical_use": "Decision support only; do not treat labels or predictions as automatic curriculum decisions.",
            }
        else:
            dataset_card = {
                "name": "FUTURE rule-assisted confirmed alignment labels",
                "purpose": "Technical development, class-balance assessment and supervised pipeline testing",
                "unit_of_analysis": "one curriculum evidence unit paired with one labour-market skill",
                "label_provenance": "deterministic transparent lexical rule proposal explicitly confirmed in the portal",
                "dataset_mode": "rule_assisted_confirmed",
                "independent_expert_validation": False,
                "limitations": [
                    "These rows are not independent expert judgements.",
                    "Lexical rules can miss semantic equivalence and contextual evidence.",
                    "Report separately from paired-review labels and retain the rule version and confirmation audit.",
                ],
                "ethical_use": "Model-development and technical validation only; do not claim independent empirical validation.",
            }
        snapshot = LabelDatasetSnapshot(
            snapshot_version=f"alignment_labels_{now.strftime('%Y%m%d_%H%M%S_%f')}",
            dataset_fingerprint=fingerprint,
            lifecycle_state="approved_locked",
            dataset_mode=dataset_mode,
            row_count=len(row_payloads),
            locked_at=now,
            locked_by=actor_id,
            label_rubric=self.RUBRIC,
            inclusion_rules=self.inclusion_rules(dataset_mode),
            exclusion_summary=dict(excluded),
            feature_schema=self.FEATURE_SCHEMA,
            manifest=manifest,
            dataset_card=dataset_card,
            sample_definition=sample_definition,
            agreement_statistics=agreement_statistics,
            notes=notes,
        )
        db.add(snapshot)
        db.flush()
        for index, payload in enumerate(row_payloads):
            labels = payload["labels"]
            curriculum_hash = self.fingerprint(payload["curriculum_evidence"])
            row_fingerprint = self.fingerprint(payload)
            db.add(
                LabelDatasetSnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    row_index=index,
                    task_id=uuid.UUID(str(payload["task_id"])),
                    document_id=uuid.UUID(str(payload["document_id"])),
                    version_id=uuid.UUID(str(payload["version_id"])),
                    chunk_id=uuid.UUID(str(payload["chunk_id"])) if payload.get("chunk_id") else None,
                    evidence_window_hash=payload["evidence_window_hash"],
                    curriculum_evidence_hash=curriculum_hash,
                    final_alignment_label=payload["final_alignment_label"],
                    label_ids=[label["label_id"] for label in labels],
                    reviewer_ids=[label["reviewer_id"] for label in labels],
                    row_payload=payload,
                    row_fingerprint=row_fingerprint,
                )
            )
        db.commit()
        db.refresh(snapshot)
        return {**self.to_dict(snapshot), "reused_identical_snapshot": False}

    def latest_locked(self, db: Session, dataset_mode: Optional[str] = None):
        query = db.query(LabelDatasetSnapshot).filter(
            LabelDatasetSnapshot.lifecycle_state == "approved_locked"
        )
        if dataset_mode:
            query = query.filter(LabelDatasetSnapshot.dataset_mode == dataset_mode)
        return query.order_by(LabelDatasetSnapshot.created_at.desc()).first()

    def list_snapshots(self, db: Session, limit: int = 25, dataset_mode: Optional[str] = None):
        query = db.query(LabelDatasetSnapshot)
        if dataset_mode:
            query = query.filter(LabelDatasetSnapshot.dataset_mode == dataset_mode)
        return query.order_by(
            LabelDatasetSnapshot.created_at.desc()
        ).limit(max(1, min(limit, 100))).all()

    def to_dict(self, snapshot: LabelDatasetSnapshot) -> Dict[str, Any]:
        return {
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_version": snapshot.snapshot_version,
            "dataset_fingerprint": snapshot.dataset_fingerprint,
            "lifecycle_state": snapshot.lifecycle_state,
            "dataset_mode": snapshot.dataset_mode,
            "row_count": snapshot.row_count,
            "locked_at": snapshot.locked_at.isoformat() if snapshot.locked_at else None,
            "locked_by": snapshot.locked_by,
            "label_rubric": snapshot.label_rubric,
            "inclusion_rules": snapshot.inclusion_rules,
            "exclusion_summary": snapshot.exclusion_summary,
            "feature_schema": snapshot.feature_schema,
            "manifest": snapshot.manifest,
            "dataset_card": snapshot.dataset_card,
            "sample_definition": snapshot.sample_definition,
            "agreement_statistics": snapshot.agreement_statistics,
            "notes": snapshot.notes,
            "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        }

    @staticmethod
    def inclusion_rules(dataset_mode: str = "technical_uat_researcher_operated") -> Dict[str, Any]:
        if dataset_mode == "independent_expert_validation":
            return {
                "expert_inclusion_rule": "two distinct named independent experts",
                "independent_experts": True,
            }
        if dataset_mode == "rule_assisted_confirmed":
            return {
                "task_status": "completed",
                "final_label_required": True,
                "deterministic_rule_proposal_required": True,
                "explicit_portal_confirmation_required": True,
                "rule_version_required": True,
                "generated_model_scores_allowed": False,
                "reviewer_persona": "rule_assisted_portal_confirmation",
                "independent_experts": False,
            }
        return {
            "task_status": "completed",
            "final_label_required": True,
            "first_review_required": True,
            "second_review_required": True,
            "distinct_reviewer_identities": True,
            "adjudication_required_on_disagreement": True,
            "generated_model_scores_allowed": False,
            "reviewer_persona": "researcher_operated_uat",
            "independent_experts": False,
        }

    def _agreement_statistics(self, row_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        first_votes: List[int] = []
        second_votes: List[int] = []
        paired = 0
        for row in row_payloads:
            first = next(
                (label["alignment_label"] for label in row.get("labels", []) if label["review_stage"] == "first"),
                None,
            )
            second = next(
                (label["alignment_label"] for label in row.get("labels", []) if label["review_stage"] == "second"),
                None,
            )
            if first is not None and second is not None:
                paired += 1
                first_votes.append(int(first))
                second_votes.append(int(second))
        if paired < 2:
            return {
                "paired_reviews": paired,
                "agreements": 0,
                "agreement_rate": None,
                "cohens_kappa": None,
                "kappa_interpretation": None,
                "confusion_matrix": {"labels": [], "cell_totals": {}, "total": 0},
            }
        agreements = sum(1 for a, b in zip(first_votes, second_votes) if a == b)
        categories = sorted({int(value) for value in first_votes} | {int(value) for value in second_votes})
        observed = agreements / paired
        first_counts = Counter(first_votes)
        second_counts = Counter(second_votes)
        expected = sum(
            first_counts.get(category, 0) / paired * second_counts.get(category, 0) / paired
            for category in categories
        )
        if abs(1.0 - expected) < 1e-9:
            kappa, interpretation = None, "expected_agreement_unity"
        else:
            kappa = round((observed - expected) / (1.0 - expected), 4)
            interpretation = next(
                (
                    name
                    for bound, name in [
                        (0.81, "almost_perfect"),
                        (0.61, "substantial"),
                        (0.41, "moderate"),
                        (0.21, "fair"),
                        (0.0, "slight"),
                        (-1.0, "poor"),
                    ]
                    if kappa >= bound
                ),
                "poor",
            )
        cells = Counter()
        for a, b in zip(first_votes, second_votes):
            cells[(int(a), int(b))] += 1

        def label_map(labels: List[int]) -> Dict[str, int]:
            return {str(key): value for key, value in sorted(Counter(labels).items())}

        return {
            "paired_reviews": paired,
            "agreements": agreements,
            "agreement_rate": round(agreements / paired, 4),
            "cohens_kappa": kappa,
            "kappa_interpretation": interpretation,
            "confusion_matrix": {
                "labels": categories,
                "cell_totals": {f"{a}|{b}": cells[(a, b)] for a in categories for b in categories},
                "row_totals": label_map(first_votes),
                "column_totals": label_map(second_votes),
                "total": paired,
            },
        }

    def _sample_definition(self, row_payloads: List[Dict[str, Any]], dataset_mode: str) -> Dict[str, Any]:
        seeds = sorted(
            {
                str((row.get("evidence_metadata") or {}).get("sample", {}).get("sample_seed") or "")
                for row in row_payloads
            }
        )
        personas = sorted(
            {
                str(label.get("reviewer_persona") or "")
                for row in row_payloads
                for label in row.get("labels", [])
            }
        )
        return {
            "dataset_mode": dataset_mode,
            "sampling_policy": "deterministic_stratified_by_subject_and_demand_band",
            "sample_seeds": seeds,
            "reviewer_personas": personas,
            "assigned_reviewer_policy": (
                "researcher_operated_uat_accounts_uq58x_untrusted"
                if dataset_mode == "technical_uat_researcher_operated"
                else ("independent_expert_validation" if dataset_mode == "independent_expert_validation" else "rule_assisted_portal_confirmation")
            ),
            "strata": sorted({str(row.get("stratum") or "") for row in row_payloads}),
        }

    def export_snapshot(self, db: Session, snapshot_id: Any, include_text: bool = True) -> Dict[str, Any]:
        snapshot = db.query(LabelDatasetSnapshot).filter(
            LabelDatasetSnapshot.snapshot_id == uuid.UUID(str(snapshot_id)),
            LabelDatasetSnapshot.lifecycle_state == "approved_locked",
        ).first()
        if not snapshot:
            raise ValueError("Approved locked label snapshot not found")
        rows = (
            db.query(LabelDatasetSnapshotRow)
            .filter(LabelDatasetSnapshotRow.snapshot_id == snapshot.snapshot_id)
            .order_by(LabelDatasetSnapshotRow.row_index.asc())
            .all()
        )
        records = []
        for row in rows:
            payload = dict(row.row_payload or {})
            record = {
                "row_index": row.row_index,
                "task_id": row.task_id,
                "document_id": row.document_id,
                "version_id": row.version_id,
                "dataset_mode": payload.get("dataset_mode") or snapshot.dataset_mode,
                "stratum": payload.get("stratum"),
                "sample_seed": payload.get("sample_seed"),
                "final_alignment_label": row.final_alignment_label,
                "subject_code": (payload.get("evidence_metadata") or {}).get("subject_code"),
                "first_review": next(
                    (label for label in payload.get("labels", []) if label.get("review_stage") == "first"),
                    None,
                ),
                "second_review": next(
                    (label for label in payload.get("labels", []) if label.get("review_stage") == "second"),
                    None,
                ),
            }
            if include_text:
                record["curriculum_evidence"] = payload.get("curriculum_evidence")
                record["labour_market_evidence"] = payload.get("labour_market_evidence") or []
            records.append(record)
        return {
            **self.to_dict(snapshot),
            "records": records,
            "export_format": "json",
            "include_evidence_text": include_text,
        }

    @staticmethod
    def fingerprint(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


label_dataset_snapshot_service = LabelDatasetSnapshotService()
