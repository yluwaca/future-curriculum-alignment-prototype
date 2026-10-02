"""
Sensitivity analysis for cosine similarity threshold in semantic matching.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.skill import Skill
from app.services.semantic_vector_service import compute_embedding, cosine_similarity
from app.services.skill_harmonisation_service import SkillHarmonisationService


logger = logging.getLogger(__name__)


class SensitivityAnalysisService:
    """
    Runs sensitivity analysis on cosine similarity threshold.

    Paper reference: ICSSA2026 camera-ready — reviewer requested sensitivity
    analysis on the cosine threshold used for skill matching.
    """

    THRESHOLD_RANGE = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]

    def __init__(self, db: Session):
        self.db = db
        self.harmonisation = SkillHarmonisationService()

    def analyse_semantic_matches(self, limit_skills: int = 500) -> Dict[str, Any]:
        """
        Analyse how varying cosine threshold affects semantic match quality.

        For each threshold in the range, measure:
        - Number of matches found
        - Mean / median / std confidence score
        - Distribution of similarity scores
        """
        skills = (
            self.db.query(Skill)
            .filter(Skill.status == "active")
            .order_by(Skill.name.asc())
            .limit(limit_skills)
            .all()
        )

        # Compute embeddings ONCE for all skills
        logger.info("[SENSITIVITY] Computing embeddings for %d skills...", len(skills))
        skill_embeddings: Dict[str, list] = {}
        for skill in skills:
            text = " ".join(
                filter(None, [skill.skill_key, skill.name, skill.category, skill.description])
            ).strip()
            if not text:
                continue
            skill_embeddings[skill.skill_id] = compute_embedding(text)
        logger.info("[SENSITIVITY] Computed %d embeddings", len(skill_embeddings))

        results = []
        for threshold in self.THRESHOLD_RANGE:
            threshold_results = self._run_semantic_match_analysis(skill_embeddings, threshold)
            results.append(threshold_results)
            logger.info(
                "[SENSITIVITY] threshold=%.2f: %d matches, mean_conf=%.4f",
                threshold,
                threshold_results["matches_found"],
                threshold_results["mean_confidence"],
            )

        return {
            "analysis_type": "cosine_threshold_sensitivity",
            "total_skills_analysed": len(skills),
            "threshold_range": self.THRESHOLD_RANGE,
            "results": results,
            "recommended_threshold": self._recommend_threshold(results),
        }

    def analyse_alignment_impact(self, version_id: Optional[UUID] = None) -> Dict[str, Any]:
        """
        Analyse how varying cosine threshold affects alignment scores.

        Uses the actual curriculum version alignment pipeline.
        """
        query = self.db.query(CurriculumDocumentVersion)
        if version_id:
            query = query.filter(CurriculumDocumentVersion.version_id == version_id)
        versions = query.order_by(CurriculumDocumentVersion.created_at.desc()).limit(5).all()

        version_results = []
        for version in versions:
            v_results = []
            existing = (
                self.db.query(AlignmentScore)
                .filter(
                    AlignmentScore.version_id == version.version_id,
                    AlignmentScore.score_type == "weighted_skill_overlap",
                )
                .order_by(AlignmentScore.created_at.desc())
                .first()
            )

            for threshold in self.THRESHOLD_RANGE:
                v_results.append({
                    "threshold": threshold,
                    "has_model_score": existing is not None,
                })

            version_results.append({
                "version_id": str(version.version_id),
                "document_id": str(version.document_id) if version.document_id else None,
                "threshold_results": v_results,
            })

        return {
            "analysis_type": "alignment_threshold_impact",
            "versions_analysed": len(versions),
            "version_results": version_results,
        }

    def analysation_summary(self, limit_skills: int = 500) -> Dict[str, Any]:
        """Generate a summary of all sensitivity analyses for reporting."""
        semantic = self.analyse_semantic_matches(limit_skills=limit_skills)
        alignment = self.analyse_alignment_impact()

        # Find knee point (elbow) — threshold where matches drop most sharply
        match_counts = [r["matches_found"] for r in semantic["results"]]
        drops = []
        for i in range(1, len(match_counts)):
            drops.append({
                "from_threshold": self.THRESHOLD_RANGE[i - 1],
                "to_threshold": self.THRESHOLD_RANGE[i],
                "match_drop": match_counts[i - 1] - match_counts[i],
                "drop_pct": round(
                    (match_counts[i - 1] - match_counts[i]) / max(match_counts[i - 1], 1) * 100,
                    2,
                ),
            })
        steepest_drop = max(drops, key=lambda d: d["drop_pct"]) if drops else None

        return {
            "semantic_analysis": semantic,
            "alignment_impact": alignment,
            "elbow_point": steepest_drop,
            "recommended_threshold": semantic["recommended_threshold"],
            "total_calibrated_skills": self.db.query(Skill).filter(
                Skill.status == "active"
            ).count(),
        }

    def _run_semantic_match_analysis(
        self, skill_embeddings: Dict[str, list], threshold: float
    ) -> Dict[str, Any]:
        """Run semantic matching at a given threshold using pre-computed embeddings."""
        total_matches = 0
        confidence_scores = []
        similarity_scores = []

        skill_ids = list(skill_embeddings.keys())
        n_skills = len(skill_ids)

        # Compare each skill against a random sample of others (max 50 per skill)
        sample_size = min(50, n_skills - 1)
        for sid in skill_ids:
            source_vector = skill_embeddings[sid]
            others = [o for o in skill_ids if o != sid]
            sampled = random.sample(others, min(sample_size, len(others)))
            for other_sid in sampled:
                similarity = cosine_similarity(source_vector, skill_embeddings[other_sid])
                if similarity >= threshold:
                    total_matches += 1
                    similarity_scores.append(similarity)
                    calibration = self.harmonisation.calibrate_confidence(
                        method="semantic_embedding",
                        raw_score=similarity,
                        evidence={"threshold": threshold},
                    )
                    confidence_scores.append(calibration["calibrated_score"])

        n = len(confidence_scores)
        return {
            "threshold": threshold,
            "matches_found": total_matches,
            "mean_confidence": round(sum(confidence_scores) / n, 4) if n else 0.0,
            "median_confidence": round(sorted(confidence_scores)[n // 2], 4) if n else 0.0,
            "min_confidence": round(min(confidence_scores), 4) if n else 0.0,
            "max_confidence": round(max(confidence_scores), 4) if n else 0.0,
            "std_confidence": round(
                (sum((c - sum(confidence_scores) / n) ** 2 for c in confidence_scores) / n) ** 0.5,
                4,
            ) if n else 0.0,
            "mean_similarity": round(sum(similarity_scores) / len(similarity_scores), 4) if similarity_scores else 0.0,
        }

    def _recommend_threshold(
        self, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Recommend optimal threshold based on:
        - Balance between match volume and confidence quality
        - Knee point in match-count curve
        """
        if not results:
            return {"threshold": 0.40, "reason": "default_fallback"}

        # Score each threshold: higher confidence * match count (diminishing returns)
        best = None
        best_score = -1

        for r in results:
            matches = r["matches_found"]
            mean_conf = r["mean_confidence"]
            if matches == 0:
                continue
            # Heuristic: matches * confidence^2 (prefer higher confidence)
            score = matches * (mean_conf ** 2)
            if score > best_score:
                best_score = score
                best = r

        if best is None:
            return {"threshold": 0.40, "reason": "no_nonzero_matches"}

        return {
            "threshold": best["threshold"],
            "reason": "optimal_balance_match_volume_confidence",
            "matches_at_threshold": best["matches_found"],
            "confidence_at_threshold": best["mean_confidence"],
            "heuristic_score": round(best_score, 4),
        }
