"""
Processing phase orchestration.

This service starts where ingestion now ends. It uses existing cleaning,
normalisation, skill, analytics, and reporting services to produce a canonical
processing snapshot that can be inspected from the portal and API docs.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_module import CurriculumModule
from app.models.document_chunk import DocumentChunk
from app.models.forecast import Forecast
from app.models.generated_report import GeneratedReport
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.models.recommendation import Recommendation
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.services.analytics_recommendation_service import analytics_recommendation_service
from app.services.curriculum_quality_service import curriculum_quality_service
from app.services.labour_market_skill_pipeline_service import labour_market_skill_pipeline_service
from app.services.labour_market_trend_service import labour_market_trend_service
from app.services.skill_harmonisation_service import skill_harmonisation_service


def stable_payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8"),
    ).hexdigest()


class ProcessingOrchestratorService:
    """
    Runs and summarises the processing handoff from ingested evidence to
    canonical facts and early intelligence outputs.
    """

    def summary(self, db: Session) -> Dict[str, Any]:
        counts = self.counts(db)
        curriculum_quality = curriculum_quality_service.summary(db)
        skills_summary = skill_harmonisation_service.summary(db)
        readiness = self.readiness(counts, curriculum_quality, skills_summary)
        processing_report_types = [
            "processing_full_run",
            "processing_readiness",
            "processing_alignment_rerun",
            "processing_forecast_rerun",
            "processing_recommendation_rerun",
        ]
        latest_report = (
            db.query(GeneratedReport)
            .filter(GeneratedReport.report_type.in_(processing_report_types))
            .order_by(GeneratedReport.created_at.desc())
            .first()
        )
        latest_reports = (
            db.query(GeneratedReport)
            .filter(GeneratedReport.report_type.in_(processing_report_types))
            .order_by(GeneratedReport.created_at.desc())
            .limit(10)
            .all()
        )
        return {
            "phase": "processing",
            "readiness": readiness,
            "counts": counts,
            "curriculum_quality": curriculum_quality,
            "skills": skills_summary,
            "latest_report_id": str(latest_report.report_id) if latest_report else None,
            "latest_report_created_at": latest_report.created_at if latest_report else None,
            "latest_processing_reports": [
                {
                    "report_id": str(report.report_id),
                    "report_type": report.report_type,
                    "title": report.title,
                    "status": report.status,
                    "summary": report.summary,
                    "created_at": report.created_at,
                }
                for report in latest_reports
            ],
        }

    def run(
        self,
        db: Session,
        actor_id: Optional[str] = None,
        limit: int = 10000,
        horizon_periods: int = 4,
        run_analytics: bool = True,
    ) -> Dict[str, Any]:
        before = self.counts(db)

        job_pipeline = labour_market_skill_pipeline_service.run(
            db=db,
            limit=limit,
            actor_id=actor_id,
        )

        trend_normalisation = labour_market_trend_service.normalise_from_cleaned_records(
            db=db,
            limit=limit,
            actor_id=actor_id,
        )
        db.commit()

        signal_generation = labour_market_trend_service.generate_signals(
            db=db,
            limit=max(limit, 50000),
            actor_id=actor_id,
        )
        db.commit()

        analytics = (
            analytics_recommendation_service.generate_all(
                db=db,
                horizon_periods=horizon_periods,
            )
            if run_analytics
            else {"skipped": True}
        )

        after = self.counts(db)
        curriculum_quality = curriculum_quality_service.summary(db)
        skills_summary = skill_harmonisation_service.summary(db)
        readiness = self.readiness(after, curriculum_quality, skills_summary)

        payload = {
            "before": before,
            "after": after,
            "job_pipeline": job_pipeline,
            "trend_normalisation": trend_normalisation,
            "signal_generation": signal_generation,
            "analytics": analytics,
            "curriculum_quality": curriculum_quality,
            "skills": skills_summary,
            "readiness": readiness,
        }

        report = self.persist_processing_report(
            db=db,
            actor_id=actor_id,
            report_type="processing_full_run" if run_analytics else "processing_readiness",
            title="Processing Full Pipeline Run" if run_analytics else "Processing Readiness Check",
            stage_key="full_pipeline" if run_analytics else "readiness_check",
            before=before,
            after=after,
            payload=payload,
            readiness=readiness,
            notes="Generated from processing orchestrator run.",
        )

        return {
            "report_id": str(report.report_id),
            "report_type": report.report_type,
            "readiness": readiness,
            "before": before,
            "after": after,
            "job_pipeline": job_pipeline,
            "trend_normalisation": trend_normalisation,
            "signal_generation": signal_generation,
            "analytics": analytics,
        }

    def run_full_pipeline(
        self,
        db: Session,
        actor_id: Optional[str] = None,
        limit: int = 10000,
        horizon_periods: int = 4,
    ) -> Dict[str, Any]:
        return self.run(
            db=db,
            actor_id=actor_id,
            limit=limit,
            horizon_periods=horizon_periods,
            run_analytics=True,
        )

    def rerun_alignment(
        self,
        db: Session,
        actor_id: Optional[str] = None,
        version_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        before = self.counts(db)
        result = analytics_recommendation_service.generate_alignment_scores(db=db, version_id=version_id)
        after = self.counts(db)
        return self.persist_stage_result(
            db=db,
            actor_id=actor_id,
            report_type="processing_alignment_rerun",
            title="Processing Rerun: Alignment Scores",
            stage_key="alignment",
            before=before,
            after=after,
            result=result,
        )

    def rerun_forecasts(
        self,
        db: Session,
        actor_id: Optional[str] = None,
        horizon_periods: int = 4,
    ) -> Dict[str, Any]:
        before = self.counts(db)
        result = analytics_recommendation_service.generate_forecasts(db=db, horizon_periods=horizon_periods)
        after = self.counts(db)
        return self.persist_stage_result(
            db=db,
            actor_id=actor_id,
            report_type="processing_forecast_rerun",
            title="Processing Rerun: Forecasts",
            stage_key="forecasts",
            before=before,
            after=after,
            result=result,
        )

    def rerun_recommendations(
        self,
        db: Session,
        actor_id: Optional[str] = None,
        version_id: Optional[Any] = None,
    ) -> Dict[str, Any]:
        before = self.counts(db)
        result = analytics_recommendation_service.generate_recommendations(db=db, version_id=version_id)
        after = self.counts(db)
        return self.persist_stage_result(
            db=db,
            actor_id=actor_id,
            report_type="processing_recommendation_rerun",
            title="Processing Rerun: Recommendations",
            stage_key="recommendations",
            before=before,
            after=after,
            result=result,
        )

    def persist_stage_result(
        self,
        db: Session,
        actor_id: Optional[str],
        report_type: str,
        title: str,
        stage_key: str,
        before: Dict[str, int],
        after: Dict[str, int],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        curriculum_quality = curriculum_quality_service.summary(db)
        skills_summary = skill_harmonisation_service.summary(db)
        readiness = self.readiness(after, curriculum_quality, skills_summary)
        payload = {
            "stage_key": stage_key,
            "before": before,
            "after": after,
            "delta": self.count_delta(before, after),
            "result": result,
            "readiness": readiness,
            "curriculum_quality": curriculum_quality,
            "skills": skills_summary,
        }
        report = self.persist_processing_report(
            db=db,
            actor_id=actor_id,
            report_type=report_type,
            title=title,
            stage_key=stage_key,
            before=before,
            after=after,
            payload=payload,
            readiness=readiness,
            notes=f"Generated from processing {stage_key} rerun.",
        )
        return {
            "report_id": str(report.report_id),
            "report_type": report.report_type,
            "stage_key": stage_key,
            "result": result,
            "before": before,
            "after": after,
            "delta": payload["delta"],
            "readiness": readiness,
        }

    def persist_processing_report(
        self,
        db: Session,
        actor_id: Optional[str],
        report_type: str,
        title: str,
        stage_key: str,
        before: Dict[str, int],
        after: Dict[str, int],
        payload: Dict[str, Any],
        readiness: Dict[str, Any],
        notes: str,
    ) -> GeneratedReport:
        payload = {
            **payload,
            "stage_key": stage_key,
            "delta": self.count_delta(before, after),
        }
        report = GeneratedReport(
            report_type=report_type,
            source_entity_type="processing_phase",
            source_entity_id=None,
            generated_by=actor_id,
            status="generated",
            title=title,
            summary={
                "stage_key": stage_key,
                "readiness_status": readiness["status"],
                "ready_checks": readiness["ready_checks"],
                "warning_checks": readiness["warning_checks"],
                "blocking_checks": readiness["blocking_checks"],
                "before_counts": before,
                "after_counts": after,
                "delta": self.count_delta(before, after),
            },
            payload=payload,
            payload_hash=stable_payload_hash(payload),
            format_hint="json",
            notes=notes,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report

    @staticmethod
    def count_delta(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
        keys = sorted(set(before) | set(after))
        return {key: int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0) for key in keys}

    def counts(self, db: Session) -> Dict[str, int]:
        return {
            "curriculum_documents": db.query(func.count(CurriculumDocument.document_id)).scalar() or 0,
            "curriculum_modules": db.query(func.count(CurriculumModule.module_id)).scalar() or 0,
            "document_chunks": db.query(func.count(DocumentChunk.chunk_id)).scalar() or 0,
            "job_postings": db.query(func.count(JobPosting.posting_id)).scalar() or 0,
            "cleaned_records": db.query(func.count(CleanedIngestionRecord.cleaned_record_id)).scalar() or 0,
            "labour_market_trends": db.query(func.count(LabourMarketTrend.trend_id)).scalar() or 0,
            "labour_market_signals": db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0,
            "skill_mappings": db.query(func.count(SkillMapping.mapping_id)).scalar() or 0,
            "curriculum_skill_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.source_domain == "curriculum")
                .scalar()
                or 0
            ),
            "labour_market_skill_mappings": (
                db.query(func.count(SkillMapping.mapping_id))
                .filter(SkillMapping.source_domain == "labour_market")
                .scalar()
                or 0
            ),
            "skill_demand_evidence": db.query(func.count(SkillDemandEvidence.evidence_id)).scalar() or 0,
            "alignment_scores": db.query(func.count(AlignmentScore.alignment_id)).scalar() or 0,
            "forecasts": db.query(func.count(Forecast.forecast_id)).scalar() or 0,
            "recommendations": db.query(func.count(Recommendation.recommendation_id)).scalar() or 0,
        }

    def readiness(
        self,
        counts: Dict[str, int],
        curriculum_quality: Dict[str, Any],
        skills_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        checks = [
            self.check("curriculum_documents", counts["curriculum_documents"] > 0, "Curriculum evidence exists."),
            self.check("document_chunks", counts["document_chunks"] > 0, "Curriculum text chunks exist."),
            self.check("job_postings", counts["job_postings"] > 0, "Current-job evidence exists."),
            self.check("cleaned_records", counts["cleaned_records"] > 0, "Cleaned model-ready records exist."),
            self.check("labour_market_signals", counts["labour_market_signals"] > 0, "Canonical labour-market demand signals exist."),
            self.check("skill_mappings", counts["skill_mappings"] > 0, "Skill mappings exist."),
            self.check(
                "curriculum_skill_mappings",
                counts["curriculum_skill_mappings"] > 0,
                "Curriculum skills are mapped.",
                warning_only=True,
            ),
            self.check(
                "skill_demand_evidence",
                counts["skill_demand_evidence"] > 0,
                "Skill demand evidence exists.",
            ),
            self.check(
                "curriculum_quality",
                float(curriculum_quality.get("quality_score") or 0) >= 0.35,
                "Curriculum quality score is usable for early alignment.",
                warning_only=True,
            ),
            self.check(
                "candidate_mapping_review",
                int(skills_summary.get("candidate_mappings") or 0) == 0,
                "No candidate skill mappings are waiting for review.",
                warning_only=True,
            ),
        ]
        blocking = [item for item in checks if item["status"] == "blocking"]
        warnings = [item for item in checks if item["status"] == "warning"]
        ready = [item for item in checks if item["status"] == "ready"]
        if blocking:
            status = "blocked"
        elif warnings:
            status = "ready_with_warnings"
        else:
            status = "ready"
        return {
            "status": status,
            "ready_checks": len(ready),
            "warning_checks": len(warnings),
            "blocking_checks": len(blocking),
            "checks": checks,
            "next_focus": [
                "Review candidate skill mappings.",
                "Improve curriculum quality by programme/module.",
                "Generate weighted alignment scores.",
                "Classify missing, weak, and strong skills.",
            ],
        }

    @staticmethod
    def check(
        key: str,
        passed: bool,
        message: str,
        warning_only: bool = False,
    ) -> Dict[str, Any]:
        if passed:
            status = "ready"
        elif warning_only:
            status = "warning"
        else:
            status = "blocking"
        return {
            "key": key,
            "status": status,
            "message": message,
        }


processing_orchestrator_service = ProcessingOrchestratorService()
