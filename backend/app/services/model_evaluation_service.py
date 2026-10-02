
"""
Model readiness and evaluation reporting.

This does not claim production XGBoost/LSTM quality before the data supports it.
It records transparent baseline metrics, data sufficiency, and next training gates.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.curriculum_document import CurriculumDocument
from app.models.document_chunk import DocumentChunk
from app.models.forecast import Forecast
from app.models.generated_report import GeneratedReport
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.recommendation import Recommendation
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping


def payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class ModelEvaluationService:
    def readiness(self, db: Session) -> Dict[str, Any]:
        counts = self.counts(db)
        latest_alignment = (
            db.query(AlignmentScore)
            .order_by(AlignmentScore.created_at.desc())
            .limit(200)
            .all()
        )
        latest_forecasts = (
            db.query(Forecast)
            .order_by(Forecast.created_at.desc())
            .limit(500)
            .all()
        )
        alignment_methods = Counter(row.model_version for row in latest_alignment)
        forecast_methods = Counter(row.method for row in latest_forecasts)
        avg_alignment_conf = self.average([row.confidence_score for row in latest_alignment])
        avg_forecast_conf = self.average([row.confidence_score for row in latest_forecasts])

        gates = [
            self.gate("curriculum_documents", counts["curriculum_documents"] >= 10, "At least 10 curriculum documents for cross-programme validation."),
            self.gate("document_chunks", counts["document_chunks"] >= 500, "At least 500 curriculum chunks for robust feature extraction."),
            self.gate("job_postings", counts["job_postings"] >= 1000, "At least 1,000 job postings for labour-market skill demand features."),
            self.gate("skill_demand_evidence", counts["skill_demand_evidence"] >= 1000, "At least 1,000 skill-demand evidence rows for model training."),
            self.gate("labour_market_signals", counts["labour_market_signals"] >= 500, "At least 500 canonical signals for forecasting."),
            self.gate("alignment_labels", counts["reviewed_recommendations"] >= 100, "At least 100 human-reviewed recommendations/labels for supervised alignment tuning."),
            self.gate("forecast_history", counts["forecasts"] >= 200, "At least 200 historical forecast outputs for backtesting/drift checks."),
        ]
        ready = [item for item in gates if item["status"] == "ready"]
        blocked = [item for item in gates if item["status"] == "blocked"]
        maturity = "trainable_candidate" if len(blocked) <= 2 else "baseline_only"
        if not blocked:
            maturity = "ready_for_ml_training"

        return {
            "model_maturity": maturity,
            "current_alignment_model": "weighted_jaccard_baseline_v2" if alignment_methods else "not_generated",
            "current_forecast_model": "canonical_signal_weighted_baseline_v2" if forecast_methods else "not_generated",
            "xgboost_status": "candidate_architecture_ready" if counts["reviewed_recommendations"] >= 100 else "waiting_for_reviewed_labels",
            "lstm_status": "candidate_architecture_ready" if counts["labour_market_signals"] >= 500 and counts["forecasts"] >= 200 else "waiting_for_longer_time_series",
            "counts": counts,
            "gates": gates,
            "ready_gates": len(ready),
            "blocked_gates": len(blocked),
            "baseline_metrics": {
                "alignment_method_counts": dict(alignment_methods.most_common(10)),
                "forecast_method_counts": dict(forecast_methods.most_common(10)),
                "average_alignment_confidence": round(avg_alignment_conf, 4),
                "average_forecast_confidence": round(avg_forecast_conf, 4),
            },
            "next_model_steps": [
                "Continue cleaning and human-reviewing skill mappings and recommendations.",
                "Collect reviewed curriculum-to-skill labels for XGBoost supervised alignment.",
                "Keep historical canonical labour-market signals for LSTM/sequence backtesting.",
                "Compare trained candidates against the current transparent baselines before promotion.",
            ],
        }

    def persist_evaluation_report(
        self,
        db: Session,
        actor_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        readiness = self.readiness(db)
        report = GeneratedReport(
            report_type="model_readiness_evaluation",
            source_entity_type="model_registry",
            source_entity_id=None,
            generated_by=actor_id,
            status="generated",
            title="Model Readiness and Baseline Evaluation",
            summary={
                "model_maturity": readiness["model_maturity"],
                "xgboost_status": readiness["xgboost_status"],
                "lstm_status": readiness["lstm_status"],
                "ready_gates": readiness["ready_gates"],
                "blocked_gates": readiness["blocked_gates"],
                "current_alignment_model": readiness["current_alignment_model"],
                "current_forecast_model": readiness["current_forecast_model"],
            },
            payload=readiness,
            payload_hash=payload_hash(readiness),
            format_hint="json",
            notes="Transparent model maturity report. Baseline models remain active until trained candidates beat them.",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return {"report_id": str(report.report_id), "readiness": readiness}

    def counts(self, db: Session) -> Dict[str, int]:
        reviewed = (
            db.query(func.count(Recommendation.recommendation_id))
            .filter(Recommendation.status.in_(["approved", "rejected", "modified_pending_review", "implemented"]))
            .scalar()
            or 0
        )
        return {
            "curriculum_documents": db.query(func.count(CurriculumDocument.document_id)).scalar() or 0,
            "document_chunks": db.query(func.count(DocumentChunk.chunk_id)).scalar() or 0,
            "job_postings": db.query(func.count(JobPosting.posting_id)).scalar() or 0,
            "skill_mappings": db.query(func.count(SkillMapping.mapping_id)).scalar() or 0,
            "skill_demand_evidence": db.query(func.count(SkillDemandEvidence.evidence_id)).scalar() or 0,
            "labour_market_signals": db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0,
            "alignment_scores": db.query(func.count(AlignmentScore.alignment_id)).scalar() or 0,
            "forecasts": db.query(func.count(Forecast.forecast_id)).scalar() or 0,
            "reviewed_recommendations": reviewed,
        }

    @staticmethod
    def gate(key: str, passed: bool, message: str) -> Dict[str, Any]:
        return {"key": key, "status": "ready" if passed else "blocked", "message": message}

    @staticmethod
    def average(values: list[float]) -> float:
        cleaned = [float(value or 0.0) for value in values if value is not None]
        return sum(cleaned) / len(cleaned) if cleaned else 0.0


model_evaluation_service = ModelEvaluationService()
