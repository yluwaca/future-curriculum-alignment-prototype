"""
Production service: skill and alignment validity checks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.esco_skill import ESCOSkill
from app.models.skill import Skill
from app.models.skill_alias import SkillAlias
from app.models.skill_mapping import SkillMapping
from app.models.ofo_taxonomy import OFOSkill
from app.models.dhet_ofo import OFOEvidenceMapping
from app.services.semantic_vector_service import (compute_embedding, cosine_similarity, local_hash_embedding)
from app.services.skill_harmonisation_service import skill_harmonisation_service

logger = logging.getLogger(__name__)


class SkillAlignmentValidityService:
    """
    Adds measurable validity controls around ESCO coverage, semantic matching,
    human review, and alignment-score calibration.
    """

    def readiness(self, db: Session) -> Dict[str, Any]:
        total_skills = db.query(func.count(Skill.skill_id)).scalar() or 0
        active_skills = (
            db.query(func.count(Skill.skill_id))
            .filter(Skill.status == "active")
            .scalar()
            or 0
        )
        esco_skills = db.query(func.count(ESCOSkill.esco_skill_id)).scalar() or 0
        esco_linked_skill_ids = {
            row[0]
            for row in db.query(ESCOSkill.skill_id)
            .filter(ESCOSkill.skill_id.isnot(None))
            .distinct()
            .all()
        }
        ofo_skills = db.query(func.count(OFOSkill.ofo_skill_id)).scalar() or 0
        ofo_linked_skill_ids = {
            row[0]
            for row in db.query(OFOEvidenceMapping.canonical_skill_id)
            .filter(
                OFOEvidenceMapping.canonical_skill_id.isnot(None),
                OFOEvidenceMapping.mapping_status == "approved",
            )
            .distinct()
            .all()
        }
        aliases = db.query(func.count(SkillAlias.alias_id)).scalar() or 0
        mappings = db.query(func.count(SkillMapping.mapping_id)).scalar() or 0
        semantic_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.extraction_method.ilike("%semantic%"))
            .scalar()
            or 0
        )
        candidate_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.mapping_status == "candidate")
            .scalar()
            or 0
        )
        needs_review_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.mapping_status == "needs_review")
            .scalar()
            or 0
        )
        approved_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(SkillMapping.mapping_status == "approved")
            .scalar()
            or 0
        )
        low_confidence_mappings = (
            db.query(func.count(SkillMapping.mapping_id))
            .filter(
                SkillMapping.mapping_status.in_(["candidate", "needs_review"]),
                SkillMapping.confidence_score < 0.60,
            )
            .scalar()
            or 0
        )
        alignment_scores = db.query(func.count(AlignmentScore.alignment_id)).scalar() or 0
        calibrated_alignments = self.calibrated_alignment_count(db)

        coverage = {
            "esco_skill_coverage": self.ratio(len(esco_linked_skill_ids), active_skills),
            "ofo_skill_coverage": self.ratio(len(ofo_linked_skill_ids), active_skills),
            "any_taxonomy_coverage": self.ratio(
                len(esco_linked_skill_ids | ofo_linked_skill_ids),
                active_skills,
            ),
            "alias_per_skill": round((aliases / total_skills), 2) if total_skills else 0.0,
            "semantic_mapping_share": self.ratio(semantic_mappings, mappings),
            "approved_mapping_share": self.ratio(approved_mappings, mappings),
            "calibrated_alignment_share": self.ratio(calibrated_alignments, alignment_scores),
        }
        issue_count = 0
        issues: List[str] = []
        if coverage["esco_skill_coverage"] < 0.50:
            issue_count += 1
            issues.append("ESCO coverage is still below 50%; import a fuller ESCO taxonomy extract.")
        if coverage["alias_per_skill"] < 1.50:
            issue_count += 1
            issues.append("Alias coverage is thin; add synonyms and local labour-market terms.")
        if low_confidence_mappings:
            issue_count += 1
            issues.append("Low-confidence mappings need human review before production reporting.")
        if mappings == 0:
            issue_count += 1
            issues.append("No curriculum or labour-market evidence mappings exist; run skill extraction before coverage can be reviewed.")
        if alignment_scores and calibrated_alignments == 0:
            issue_count += 1
            issues.append("Alignment scores exist but have not yet been calibrated against expert judgement.")

        score = max(
            0.0,
            min(
                1.0,
                (
                    coverage["esco_skill_coverage"] * 0.25
                    + min(coverage["alias_per_skill"] / 3.0, 1.0) * 0.20
                    + max(coverage["approved_mapping_share"], 0.10) * 0.20
                    + max(coverage["semantic_mapping_share"], 0.10) * 0.15
                    + max(coverage["calibrated_alignment_share"], 0.10) * 0.20
                ),
            ),
        )

        return {
            "phase": "Skills Alignment Validity",
            "score": round(score, 4),
            "status": "ready" if score >= 0.75 and issue_count == 0 else "needs_attention",
            "counts": {
                "skills": total_skills,
                "active_skills": active_skills,
                "esco_skills": esco_skills,
                "esco_linked_canonical_skills": len(esco_linked_skill_ids),
                "ofo_skills": ofo_skills,
                "ofo_linked_canonical_skills": len(ofo_linked_skill_ids),
                "aliases": aliases,
                "mappings": mappings,
                "semantic_mappings": semantic_mappings,
                "candidate_mappings": candidate_mappings,
                "needs_review_mappings": needs_review_mappings,
                "approved_mappings": approved_mappings,
                "low_confidence_mappings": low_confidence_mappings,
                "alignment_scores": alignment_scores,
                "calibrated_alignments": calibrated_alignments,
            },
            "coverage": coverage,
            "issues": issues,
            "next_actions": [
                "Import or refresh ESCO taxonomy data.",
                "Run semantic matching for curriculum and labour-market evidence.",
                "Review low-confidence mappings and approve/reject them.",
                "Calibrate alignment scores with expert curriculum judgement.",
            ],
        }

    def esco_import_preview(self, records: List[Dict[str, Any]], taxonomy_version: str) -> Dict[str, Any]:
        VALID_SKILL_TYPES = {"skill/competence", "knowledge", "language", "attitude"}
        VALID_REUSE_LEVELS = {"cross-sector", "sector-specific", "occupation-specific", "transversal"}

        from app.models.esco_skill import ESCOSkill
        from app.db.session import SessionLocal

        valid_records = []
        issues = []
        existing_uris: set = set()
        existing_labels: set = set()
        try:
            with SessionLocal() as preview_db:
                for row in preview_db.query(ESCOSkill.esco_uri).filter(ESCOSkill.esco_uri.isnot(None)).all():
                    existing_uris.add(row[0])
                for row in preview_db.query(ESCOSkill.preferred_label).all():
                    existing_labels.add(row[0].lower())
        except Exception as exc:
            logger.warning("[SKILL-VALIDITY] Failed to load existing ESCO data for preview: %s", exc)

        for index, row in enumerate(records, start=1):
            label = skill_harmonisation_service.first_value(
                row,
                "preferredLabel",
                "preferred_label",
                "preferredLabel_en",
                "label",
                "title",
            )
            uri = skill_harmonisation_service.first_value(row, "conceptUri", "concept_uri", "uri", "esco_uri")
            skill_type = skill_harmonisation_service.first_value(row, "skillType", "skill_type", "type")
            reuse_level = skill_harmonisation_service.first_value(row, "reuseLevel", "reuse_level")

            if not label:
                issues.append({"row": index, "issue": "missing_preferred_label", "severity": "error"})
                continue
            if len(label) > 255:
                issues.append({"row": index, "issue": "preferred_label_too_long", "value": len(label), "severity": "warning"})

            if not uri:
                issues.append({"row": index, "issue": "missing_concept_uri", "label": label, "severity": "warning"})
            elif not uri.startswith("http"):
                issues.append({"row": index, "issue": "invalid_uri_format", "uri": uri, "severity": "warning"})
            elif uri in existing_uris:
                issues.append({"row": index, "issue": "duplicate_uri_exists", "uri": uri, "severity": "info"})

            if skill_type and skill_type not in VALID_SKILL_TYPES:
                issues.append({"row": index, "issue": "unknown_skill_type", "value": skill_type, "severity": "warning"})
            if reuse_level and reuse_level not in VALID_REUSE_LEVELS:
                issues.append({"row": index, "issue": "unknown_reuse_level", "value": reuse_level, "severity": "warning"})

            if label and label.lower() in existing_labels:
                issues.append({"row": index, "issue": "label_conflict_exists", "label": label, "severity": "info"})

            valid_records.append(
                {
                    "row": index,
                    "preferred_label": label,
                    "esco_uri": uri,
                    "skill_type": skill_type,
                    "reuse_level": reuse_level,
                }
            )

        return {
            "dry_run": True,
            "taxonomy_version": taxonomy_version,
            "records_seen": len(records),
            "valid_records": len(valid_records),
            "issues": issues[:200],
            "error_count": sum(1 for i in issues if i.get("severity") == "error"),
            "warning_count": sum(1 for i in issues if i.get("severity") == "warning"),
            "info_count": sum(1 for i in issues if i.get("severity") == "info"),
            "sample_records": valid_records[:10],
            "skills_created": 0,
            "esco_created": 0,
            "esco_updated": 0,
            "aliases_created": 0,
        }

    def semantic_candidates_for_skill(
        self,
        db: Session,
        skill_id: UUID,
        threshold: float = 0.35,
        limit: int = 10,
    ) -> Dict[str, Any]:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if not skill:
            raise ValueError("Skill not found")
        semantic_text = " ".join(filter(None, [skill.skill_key, skill.name, skill.category, skill.description]))
        source_vector = compute_embedding(semantic_text)
        candidate_rows = (
            db.query(Skill.skill_id, Skill.skill_key, Skill.name, Skill.category, Skill.description)
            .filter(Skill.status == "active", Skill.skill_id != skill.skill_id)
            .order_by(Skill.name.asc())
            .limit(1000)
            .all()
        )
        scored = []
        for row in candidate_rows:
            candidate_text = " ".join(filter(None, [row.skill_key, row.name, row.category, row.description]))
            similarity = cosine_similarity(source_vector, compute_embedding(candidate_text))
            if similarity < threshold:
                continue
            calibration = skill_harmonisation_service.calibrate_confidence(
                method="semantic_embedding",
                raw_score=similarity,
                evidence={"threshold": threshold, "inspection_mode": "skills_alignment_lightweight"},
            )
            scored.append(
                {
                    "skill_id": str(row.skill_id),
                    "skill_key": row.skill_key,
                    "name": row.name,
                    "semantic_similarity": round(similarity, 4),
                    "confidence_score": calibration["calibrated_score"],
                    "confidence_calibration": calibration,
                }
            )
        items = sorted(scored, key=lambda item: item["confidence_score"], reverse=True)[:limit]
        return {
            "source_skill": {
                "skill_id": str(skill.skill_id),
                "skill_key": skill.skill_key,
                "name": skill.name,
            },
            "threshold": threshold,
            "candidates": items,
        }

    def alignment_calibration_summary(self, db: Session, limit: int = 25) -> Dict[str, Any]:
        total = db.query(func.count(AlignmentScore.alignment_id)).scalar() or 0
        rows = (
            db.query(AlignmentScore)
            .order_by(AlignmentScore.created_at.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        calibrated = 0
        diffs = []
        samples = []
        for row in rows:
            calibration = (row.score_metadata or {}).get("calibration") or {}
            if calibration:
                calibrated += 1
            expert_score = calibration.get("expert_alignment_score")
            delta = None
            if expert_score is not None:
                delta = round(float(row.alignment_score or 0) - float(expert_score or 0), 4)
                diffs.append(abs(delta))
            samples.append(
                {
                    "alignment_id": str(row.alignment_id),
                    "score_type": row.score_type,
                    "alignment_score": row.alignment_score,
                    "gap_score": row.gap_score,
                    "confidence_score": row.confidence_score,
                    "model_version": row.model_version,
                    "status": row.status,
                    "calibration": calibration,
                    "model_vs_expert_delta": delta,
                }
            )
        return {
            "alignment_scores": total,
            "sampled": len(rows),
            "sampled_calibrated": calibrated,
            "calibrated_total_estimate": self.calibrated_alignment_count(db),
            "mean_abs_model_expert_delta": round(sum(diffs) / len(diffs), 4) if diffs else None,
            "samples": samples,
            "next_actions": [
                "Capture expert alignment scores for representative programmes/modules.",
                "Compare model score against expert score.",
                "Tune skill-gap thresholds and evidence weights where deltas remain high.",
            ],
        }

    def record_alignment_calibration(
        self,
        db: Session,
        alignment_id: UUID,
        expert_alignment_score: float,
        reviewer_id: str,
        note: Optional[str] = None,
    ) -> AlignmentScore:
        row = db.query(AlignmentScore).filter(AlignmentScore.alignment_id == alignment_id).first()
        if not row:
            raise ValueError("Alignment score not found")
        bounded = max(0.0, min(float(expert_alignment_score), 1.0))
        existing = dict(row.score_metadata or {})
        existing["calibration"] = {
            "expert_alignment_score": round(bounded, 4),
            "model_alignment_score": row.alignment_score,
            "absolute_delta": round(abs(float(row.alignment_score or 0) - bounded), 4),
            "reviewed_by": reviewer_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
            "calibration_version": "expert_alignment_calibration_v1",
        }
        row.score_metadata = existing
        row.status = "calibrated"
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def calibrated_alignment_count(self, db: Session) -> int:
        rows = db.query(AlignmentScore.score_metadata).all()
        return sum(1 for (metadata,) in rows if isinstance(metadata, dict) and metadata.get("calibration"))

    @staticmethod
    def ratio(numerator: int, denominator: int) -> float:
        return round(float(numerator or 0) / float(denominator or 1), 4)


skill_alignment_validity_service = SkillAlignmentValidityService()
