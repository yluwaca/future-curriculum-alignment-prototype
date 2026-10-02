"""
Production service: ML and recommendation quality controls.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.forecast import Forecast
from app.models.generated_report import GeneratedReport
from app.models.recommendation import Recommendation
from app.models.recommendation_explanation import RecommendationExplanation
from app.models.recommendation_review import RecommendationReview
from app.models.skill import Skill
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.services.model_evaluation_service import model_evaluation_service, payload_hash


class MLRecommendationQualityService:
    """
    Evaluates forecast quality, model registry maturity, recommendation ranking,
    and explainability coverage without claiming trained-model maturity too early.
    """

    def quality_summary(self, db: Session) -> Dict[str, Any]:
        forecast = self.forecast_evaluation(db)
        registry = self.model_registry_summary(db)
        ranking = self.recommendation_ranking_quality(db)
        explainability = self.explainability_quality(db)
        score = round(
            (
                forecast["quality_score"] * 0.25
                + registry["quality_score"] * 0.25
                + ranking["quality_score"] * 0.25
                + explainability["quality_score"] * 0.25
            ),
            4,
        )
        issues = forecast["issues"] + registry["issues"] + ranking["issues"] + explainability["issues"]
        return {
            "phase": "Forecast & Recommendation Quality",
            "score": score,
            "status": "ready" if score >= 0.75 and not issues else "needs_attention",
            "forecast_evaluation": forecast,
            "model_registry": registry,
            "recommendation_ranking": ranking,
            "explainability": explainability,
            "issues": issues[:12],
            "next_actions": [
                "Backtest forecasts against longer historical demand windows.",
                "Register each promoted baseline/trained model with metrics and data snapshot metadata.",
                "Refresh recommendation ranking after data-quality or forecast reruns.",
                "Generate explainability reports for supervisor/governance review.",
            ],
        }

    def forecast_evaluation(self, db: Session, limit: int = 500) -> Dict[str, Any]:
        rows = (
            db.query(Forecast)
            .order_by(Forecast.created_at.desc())
            .limit(limit)
            .all()
        )
        if not rows:
            return {
                "quality_score": 0.0,
                "forecast_count": 0,
                "evaluated_count": 0,
                "method_counts": {},
                "direction_counts": {},
                "average_confidence": 0.0,
                "mean_absolute_proxy_error": None,
                "issues": ["No forecast outputs are available for evaluation."],
                "samples": [],
            }

        direction_counts = Counter(row.trend_direction for row in rows)
        method_counts = Counter(row.method for row in rows)
        confidence = self.average([row.confidence_score for row in rows])
        proxy_errors = []
        samples = []
        for row in rows[:100]:
            baseline = float(row.baseline_value or 0.0)
            forecast = float(row.forecast_value or 0.0)
            denominator = max(abs(baseline), 1.0)
            proxy_error = abs(forecast - baseline) / denominator
            proxy_errors.append(proxy_error)
            payload = row.forecast_payload or {}
            samples.append(
                {
                    "forecast_id": str(row.forecast_id),
                    "skill_id": str(row.skill_id) if row.skill_id else None,
                    "method": row.method,
                    "baseline_value": row.baseline_value,
                    "forecast_value": row.forecast_value,
                    "trend_direction": row.trend_direction,
                    "confidence_score": row.confidence_score,
                    "proxy_error": round(proxy_error, 4),
                    "evidence_count": payload.get("signal_evidence", {}).get("evidence_count")
                    or payload.get("evidence_count"),
                }
            )
        mean_proxy_error = self.average(proxy_errors)
        issues = []
        if len(rows) < 200:
            issues.append("Forecast history is still shallow; backtesting confidence is limited.")
        if confidence < 0.65:
            issues.append("Average forecast confidence is below the production target of 65%.")
        if mean_proxy_error > 0.50:
            issues.append("Forecasts diverge strongly from current baseline values; inspect demand weighting.")
        quality = round(
            min(1.0, (min(len(rows), 500) / 500 * 0.35) + (confidence * 0.45) + (max(0.0, 1.0 - mean_proxy_error) * 0.20)),
            4,
        )
        return {
            "quality_score": quality,
            "forecast_count": db.query(func.count(Forecast.forecast_id)).scalar() or 0,
            "evaluated_count": len(rows),
            "method_counts": dict(method_counts.most_common(10)),
            "direction_counts": dict(direction_counts.most_common(10)),
            "average_confidence": round(confidence, 4),
            "mean_absolute_proxy_error": round(mean_proxy_error, 4),
            "issues": issues,
            "samples": samples[:25],
        }

    def model_registry_summary(self, db: Session) -> Dict[str, Any]:
        readiness = model_evaluation_service.readiness(db)
        alignment_versions = dict(
            db.query(AlignmentScore.model_version, func.count(AlignmentScore.alignment_id))
            .group_by(AlignmentScore.model_version)
            .all()
        )
        forecast_versions = dict(
            db.query(Forecast.method, func.count(Forecast.forecast_id))
            .group_by(Forecast.method)
            .all()
        )
        report_count = (
            db.query(func.count(GeneratedReport.report_id))
            .filter(GeneratedReport.source_entity_type == "model_registry")
            .scalar()
            or 0
        )
        registry_items = [
            {
                "model_key": "alignment.weighted_jaccard_baseline_v2",
                "model_family": "transparent_statistical_baseline",
                "output_table": "alignment_score",
                "versions": alignment_versions,
                "promotion_status": readiness.get("xgboost_status"),
                "successor_model": "xgboost_alignment_classifier",
            },
            {
                "model_key": "forecast.canonical_signal_weighted_baseline_v2",
                "model_family": "transparent_statistical_baseline",
                "output_table": "forecast",
                "versions": forecast_versions,
                "promotion_status": readiness.get("lstm_status"),
                "successor_model": "lstm_demand_sequence_model",
            },
            {
                "model_key": "recommendation.priority_ranker_v1",
                "model_family": "explainable_weighted_ranker",
                "output_table": "recommendation",
                "versions": {"recommendation_priority_ranker_v1": db.query(func.count(Recommendation.recommendation_id)).scalar() or 0},
                "promotion_status": "baseline_active",
                "successor_model": "learning_to_rank_recommendation_model",
            },
        ]
        issues = []
        if report_count == 0:
            issues.append("No persisted model registry/readiness report exists yet.")
        if readiness.get("model_maturity") == "baseline_only":
            issues.append("Model maturity is still baseline-only until reviewed labels and longer time series improve.")
        quality = round(
            min(1.0, (readiness.get("ready_gates", 0) / max(len(readiness.get("gates", [])), 1) * 0.65) + (0.20 if report_count else 0.0)),
            4,
        )
        return {
            "quality_score": quality,
            "model_maturity": readiness.get("model_maturity"),
            "ready_gates": readiness.get("ready_gates"),
            "blocked_gates": readiness.get("blocked_gates"),
            "registry_report_count": report_count,
            "models": registry_items,
            "issues": issues,
        }

    def recommendation_ranking_quality(self, db: Session, limit: int = 500) -> Dict[str, Any]:
        rows = (
            db.query(Recommendation)
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
            .all()
        )
        if not rows:
            return {
                "quality_score": 0.0,
                "recommendation_count": 0,
                "ranked_count": 0,
                "average_priority_score": 0.0,
                "issues": ["No recommendations are available for ranking evaluation."],
                "top_recommendations": [],
            }
        priority_counts = Counter(row.priority for row in rows)
        status_counts = Counter(row.status for row in rows)
        ranked = [row for row in rows if float(row.priority_score or 0.0) > 0]
        explainable = [row for row in rows if (row.recommendation_metadata or {}).get("ranking_factors") or (row.recommendation_metadata or {}).get("top_demand_evidence")]
        top = sorted(rows, key=lambda item: float(item.priority_score or 0.0), reverse=True)[:25]
        avg_priority = self.average([row.priority_score for row in rows])
        issues = []
        if len(ranked) < len(rows) * 0.80:
            issues.append("Some recommendations do not yet have usable priority scores.")
        if len(explainable) < len(rows) * 0.50:
            issues.append("Recommendation ranking evidence is thin for many rows.")
        if not any(key in priority_counts for key in ("high", "critical")):
            issues.append("No high-priority recommendations are currently surfaced.")
        quality = round(
            min(1.0, (len(ranked) / len(rows) * 0.35) + (len(explainable) / len(rows) * 0.35) + min(avg_priority, 1.0) * 0.30),
            4,
        )
        return {
            "quality_score": quality,
            "recommendation_count": db.query(func.count(Recommendation.recommendation_id)).scalar() or 0,
            "evaluated_count": len(rows),
            "ranked_count": len(ranked),
            "explainable_ranked_count": len(explainable),
            "average_priority_score": round(avg_priority, 4),
            "priority_counts": dict(priority_counts),
            "status_counts": dict(status_counts),
            "issues": issues,
            "top_recommendations": [
                {
                    "recommendation_id": str(row.recommendation_id),
                    "title": row.title,
                    "priority": row.priority,
                    "priority_score": row.priority_score,
                    "confidence_score": row.confidence_score,
                    "status": row.status,
                }
                for row in top
            ],
        }

    def refresh_recommendation_ranking(self, db: Session, limit: int = 500, dry_run: bool = True) -> Dict[str, Any]:
        rows = (
            db.query(Recommendation)
            .filter(Recommendation.status.in_(["pending_review", "modified_pending_review"]))
            .order_by(Recommendation.created_at.desc())
            .limit(max(1, min(limit, 5000)))
            .all()
        )
        updates = []
        for row in rows:
            metadata = dict(row.recommendation_metadata or {})
            forecast = db.query(Forecast).filter(Forecast.forecast_id == row.forecast_id).first() if row.forecast_id else None
            evidence_stats = self.skill_evidence_stats(db, row.skill_id) if row.skill_id else {"count": 0, "avg_demand": 0.0, "avg_confidence": 0.0}
            gap_factor = float(metadata.get("gap_score") or metadata.get("alignment_gap_score") or 0.0)
            demand_factor = max(float(metadata.get("skill_demand_score") or 0.0), evidence_stats["avg_demand"])
            forecast_factor = float(forecast.confidence_score or 0.0) if forecast else 0.0
            evidence_factor = min(evidence_stats["count"] / 25.0, 1.0)
            confidence_factor = max(float(row.confidence_score or 0.0), evidence_stats["avg_confidence"])
            new_score = round(
                min(1.0, (gap_factor * 0.30) + (demand_factor * 0.25) + (forecast_factor * 0.15) + (evidence_factor * 0.15) + (confidence_factor * 0.15)),
                4,
            )
            new_priority = "high" if new_score >= 0.72 else "medium" if new_score >= 0.42 else "low"
            factors = {
                "gap_factor": round(gap_factor, 4),
                "demand_factor": round(demand_factor, 4),
                "forecast_factor": round(forecast_factor, 4),
                "evidence_factor": round(evidence_factor, 4),
                "confidence_factor": round(confidence_factor, 4),
                "ranker_version": "recommendation_priority_ranker_v1",
            }
            updates.append(
                {
                    "recommendation_id": str(row.recommendation_id),
                    "old_priority": row.priority,
                    "new_priority": new_priority,
                    "old_priority_score": row.priority_score,
                    "new_priority_score": new_score,
                    "ranking_factors": factors,
                }
            )
            if not dry_run:
                row.priority = new_priority
                row.priority_score = new_score
                row.recommendation_metadata = {
                    **metadata,
                    "ranking_factors": factors,
                    "ranking_refreshed_by": "recommendation_quality",
                }
                db.add(row)
        if not dry_run:
            db.commit()
        return {
            "dry_run": dry_run,
            "recommendations_checked": len(rows),
            "recommendations_updated": 0 if dry_run else len(rows),
            "updates": updates[:100],
        }

    def explainability_quality(self, db: Session, limit: int = 500) -> Dict[str, Any]:
        recommendation_count = db.query(func.count(Recommendation.recommendation_id)).scalar() or 0
        explanation_count = db.query(func.count(RecommendationExplanation.explanation_id)).scalar() or 0
        explained_ids = {
            row[0]
            for row in (
                db.query(RecommendationExplanation.recommendation_id)
                .group_by(RecommendationExplanation.recommendation_id)
                .all()
            )
        }
        latest_recommendations = (
            db.query(Recommendation)
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
            .all()
        )
        explained_latest = sum(1 for row in latest_recommendations if row.recommendation_id in explained_ids)
        explainability_share = explained_latest / len(latest_recommendations) if latest_recommendations else 0.0
        explanation_types = dict(
            db.query(RecommendationExplanation.explanation_type, func.count(RecommendationExplanation.explanation_id))
            .group_by(RecommendationExplanation.explanation_type)
            .all()
        )
        issues = []
        if explainability_share < 0.80 and latest_recommendations:
            issues.append("Less than 80% of recent recommendations have explanation records.")
        if "rationale" not in explanation_types:
            issues.append("Rationale explanations are missing or not typed consistently.")
        quality = round(min(1.0, explainability_share * 0.75 + min(len(explanation_types), 4) / 4 * 0.25), 4)
        return {
            "quality_score": quality,
            "recommendation_count": recommendation_count,
            "explanation_count": explanation_count,
            "explained_recent_recommendations": explained_latest,
            "recent_recommendations_checked": len(latest_recommendations),
            "explainability_share": round(explainability_share, 4),
            "explanation_type_counts": explanation_types,
            "issues": issues,
        }

    def persist_explainability_report(self, db: Session, actor_id: Optional[str] = None) -> Dict[str, Any]:
        payload = self.quality_summary(db)
        report = GeneratedReport(
            report_type="ml_recommendation_quality",
            source_entity_type="model_registry",
            source_entity_id=None,
            generated_by=actor_id,
            status="generated",
            title="ML and Recommendation Quality Report",
            summary={
                "phase": payload["phase"],
                "score": payload["score"],
                "status": payload["status"],
                "forecast_quality": payload["forecast_evaluation"]["quality_score"],
                "ranking_quality": payload["recommendation_ranking"]["quality_score"],
                "explainability_quality": payload["explainability"]["quality_score"],
            },
            payload=payload,
            payload_hash=payload_hash(payload),
            format_hint="json",
            notes="ML and recommendation quality report: forecast evaluation, model registry, ranking, and explainability.",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return {"report_id": str(report.report_id), "summary": report.summary, "payload": payload}

    def skill_evidence_stats(self, db: Session, skill_id: UUID) -> Dict[str, float]:
        count, avg_demand, avg_confidence = (
            db.query(
                func.count(SkillDemandEvidence.evidence_id),
                func.avg(SkillDemandEvidence.demand_score),
                func.avg(SkillDemandEvidence.confidence_score),
            )
            .filter(SkillDemandEvidence.skill_id == skill_id)
            .first()
        )
        return {
            "count": int(count or 0),
            "avg_demand": float(avg_demand or 0.0),
            "avg_confidence": float(avg_confidence or 0.0),
        }

    @staticmethod
    def average(values: List[float]) -> float:
        cleaned = [float(value or 0.0) for value in values if value is not None]
        return sum(cleaned) / len(cleaned) if cleaned else 0.0


ml_recommendation_quality_service = MLRecommendationQualityService()
