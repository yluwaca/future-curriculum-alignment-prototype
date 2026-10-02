"""
Intelligence services for FUTURE Platform.

Implements basic versions of:
- LLM/RAG: Semantic context retrieval using sentence-transformer embeddings
- Scenario Simulation: Curriculum change impact projection
- Model Drift Monitoring: Statistical drift detection

Paper reference: ICSSA 2026 — Adaptive AI for Curriculum-Labour Market Alignment
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from scipy import stats as scipy_stats

from app.services.future_hooks.base import HookResult

logger = logging.getLogger(__name__)

SIMULATION_DISCLAIMER = (
    "Simulation-based finding; longitudinal validation pending."
)


class LLMRAGService:
    """Basic semantic context retrieval using cosine similarity on embeddings."""

    service_key = "llm_rag_service"
    capabilities = [
        "semantic_context_retrieval",
        "retrieval_augmented_generation",
        "recommendation_explanation_assistance",
    ]

    def query(
        self,
        question: str,
        context_filters: Dict[str, Any],
        top_k: int = 5,
    ) -> HookResult:
        try:
            from app.services.semantic_vector_service import compute_embedding, cosine_similarity
            from sqlalchemy.orm import Session
            from app.core.database import SessionLocal
            from app.models.curriculum_document_version import CurriculumDocumentVersion
            from app.models.recommendation import Recommendation

            db = SessionLocal()
            try:
                question_embedding = compute_embedding(question)
                if not question_embedding:
                    return HookResult(
                        status="error",
                        message="Failed to compute question embedding",
                        payload={"question": question},
                    )

                results = []

                curricula = db.query(CurriculumDocumentVersion).limit(100).all()
                for cur in curricula:
                    text = f"{cur.title or ''} {cur.description or ''}".strip()
                    if not text:
                        continue
                    cur_embedding = compute_embedding(text)
                    if cur_embedding:
                        sim = cosine_similarity(question_embedding, cur_embedding)
                        results.append({
                            "type": "curriculum",
                            "id": str(cur.version_id),
                            "title": cur.title,
                            "similarity": round(sim, 4),
                            "snippet": text[:200],
                        })

                recommendations = db.query(Recommendation).limit(100).all()
                for rec in recommendations:
                    text = f"{rec.title or ''} {rec.description or ''}".strip()
                    if not text:
                        continue
                    rec_embedding = compute_embedding(text)
                    if rec_embedding:
                        sim = cosine_similarity(question_embedding, rec_embedding)
                        results.append({
                            "type": "recommendation",
                            "id": str(rec.recommendation_id),
                            "title": rec.title,
                            "similarity": round(sim, 4),
                            "snippet": text[:200],
                        })

                results.sort(key=lambda x: x["similarity"], reverse=True)
                top_results = results[:top_k]

                return HookResult(
                    status="ok",
                    message=f"Retrieved {len(top_results)} relevant contexts",
                    payload={
                        "question": question,
                        "top_k": top_k,
                        "results": top_results,
                        "total_searched": len(results),
                    },
                )
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[LLM-RAG] Query failed: %s", exc)
            return HookResult(
                status="error",
                message=f"RAG query failed: {exc}",
                payload={"question": question},
            )


class ScenarioSimulationService:
    """Basic curriculum change simulation using gap-score projections."""

    service_key = "scenario_simulation_service"
    capabilities = [
        "curriculum_change_simulation",
        "skill_gap_impact_projection",
        "recommendation_priority_sensitivity",
    ]

    def simulate(
        self,
        scenario_name: str,
        assumptions: Dict[str, Any],
    ) -> HookResult:
        try:
            from sqlalchemy.orm import Session
            from app.core.database import SessionLocal
            from app.models.curriculum_document_version import CurriculumDocumentVersion
            from app.models.skill_demand_evidence import SkillDemandEvidence

            db = SessionLocal()
            try:
                added_skills = assumptions.get("added_skills", [])
                removed_skills = assumptions.get("removed_skills", [])
                target_module = assumptions.get("target_module", None)

                curricula = db.query(CurriculumDocumentVersion).limit(200).all()
                evidence = db.query(SkillDemandEvidence).limit(500).all()

                skill_demand = {}
                for e in evidence:
                    skill_name = getattr(e, "skill_name", None) or getattr(e, "skill", None)
                    if skill_name:
                        demand = getattr(e, "demand_score", 0.5)
                        skill_demand[skill_name] = max(skill_demand.get(skill_name, 0), float(demand))

                current_alignment = 0.0
                projected_alignment = 0.0
                matched = 0
                for cur in curricula:
                    text = (getattr(cur, "description", None) or "").lower()
                    if not text:
                        continue
                    matched += 1
                    current_skills = set()
                    for word in text.split():
                        word = word.strip(".,;:()")
                        if word in skill_demand:
                            current_skills.add(word)

                    if current_skills:
                        current_alignment += sum(skill_demand[s] for s in current_skills) / len(current_skills)

                    projected_skills = (current_skills | set(added_skills)) - set(removed_skills)
                    if projected_skills:
                        projected_alignment += sum(skill_demand.get(s, 0.1) for s in projected_skills) / len(projected_skills)

                if matched > 0:
                    current_alignment /= matched
                    projected_alignment /= matched

                delta = projected_alignment - current_alignment

                return HookResult(
                    status="ok",
                    message=f"Scenario '{scenario_name}' simulated on {matched} curricula",
                    payload={
                        "scenario_name": scenario_name,
                        "assumptions": assumptions,
                        "current_alignment": round(current_alignment, 4),
                        "projected_alignment": round(projected_alignment, 4),
                        "alignment_delta": round(delta, 4),
                        "curricula_affected": matched,
                        "skills_added": added_skills,
                        "skills_removed": removed_skills,
                        "disclaimer": SIMULATION_DISCLAIMER,
                    },
                )
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[SIMULATION] Failed: %s", exc)
            return HookResult(
                status="error",
                message=f"Simulation failed: {exc}",
                payload={
                    "scenario_name": scenario_name,
                    "disclaimer": SIMULATION_DISCLAIMER,
                },
            )


class ModelDriftMonitoringService:
    """Statistical drift detection using KS-test and rolling metrics."""

    service_key = "model_drift_monitoring"
    capabilities = [
        "feature_distribution_monitoring",
        "forecast_error_tracking",
        "alignment_score_stability_checks",
    ]

    def check(
        self,
        model_key: str,
        metric_names: List[str],
        window: str = "30d",
    ) -> HookResult:
        try:
            from sqlalchemy.orm import Session
            from app.core.database import SessionLocal
            from app.models.predictive_output import PredictiveOutput
            from app.models.forecast import Forecast
            import numpy as np

            db = SessionLocal()
            try:
                drift_results = []

                if model_key in ("xgboost", "alignment"):
                    outputs = (
                        db.query(PredictiveOutput)
                        .order_by(PredictiveOutput.prediction_timestamp.desc())
                        .limit(500)
                        .all()
                    )
                    if len(outputs) >= 20:
                        scores = [float(o.alignment_score or 0) for o in outputs if o.alignment_score is not None]
                        if len(scores) >= 20:
                            half = len(scores) // 2
                            early = scores[half:]
                            late = scores[:half]
                            ks_stat, p_value = scipy_stats.ks_2samp(early, late)
                            drift_results.append({
                                "metric": "alignment_score_distribution",
                                "ks_statistic": round(float(ks_stat), 4),
                                "p_value": round(float(p_value), 4),
                                "drifted": p_value < 0.05,
                                "early_mean": round(float(np.mean(early)), 4),
                                "late_mean": round(float(np.mean(late)), 4),
                            })

                if model_key in ("lstm", "forecast"):
                    forecasts = (
                        db.query(Forecast)
                        .order_by(Forecast.created_at.desc())
                        .limit(500)
                        .all()
                    )
                    if len(forecasts) >= 20:
                        values = [float(f.forecast_value) for f in forecasts if f.forecast_value is not None]
                        baselines = [float(f.baseline_value) for f in forecasts if f.baseline_value is not None]
                        if len(values) >= 20 and len(baselines) >= 20:
                            residuals = [abs(v - b) for v, b in zip(values[:len(baselines)], baselines)]
                            half = len(residuals) // 2
                            early_res = residuals[half:]
                            late_res = residuals[:half]
                            ks_stat, p_value = scipy_stats.ks_2samp(early_res, late_res)
                            mae = float(np.mean(residuals))
                            drift_results.append({
                                "metric": "forecast_residual_distribution",
                                "ks_statistic": round(float(ks_stat), 4),
                                "p_value": round(float(p_value), 4),
                                "drifted": p_value < 0.05,
                                "mae": round(mae, 4),
                                "early_mae": round(float(np.mean(early_res)), 4),
                                "late_mae": round(float(np.mean(late_res)), 4),
                            })

                overall_drifted = any(r.get("drifted", False) for r in drift_results)

                return HookResult(
                    status="ok",
                    message=f"Drift check completed for {model_key}: {'DRIFT DETECTED' if overall_drifted else 'STABLE'}",
                    payload={
                        "model_key": model_key,
                        "window": window,
                        "overall_drifted": overall_drifted,
                        "checks": drift_results,
                        "check_count": len(drift_results),
                    },
                )
            finally:
                db.close()
        except Exception as exc:
            logger.warning("[DRIFT] Check failed: %s", exc)
            return HookResult(
                status="error",
                message=f"Drift check failed: {exc}",
                payload={"model_key": model_key, "window": window},
            )


llm_rag_service = LLMRAGService()
scenario_simulation_service = ScenarioSimulationService()
model_drift_monitoring_service = ModelDriftMonitoringService()
