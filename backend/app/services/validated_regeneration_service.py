"""Regenerate decision outputs only from validated, traceable evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.alignment_score import AlignmentScore
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_evidence_review import CurriculumEvidenceReview
from app.models.forecast import Forecast
from app.models.generated_report import GeneratedReport
from app.models.labour_market_signal import LabourMarketSignal
from app.models.job_posting import JobPosting
from app.models.recommendation import Recommendation
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.skill_mapping import SkillMapping
from app.services.analytics_recommendation_service import analytics_recommendation_service


class ValidatedRegenerationService:
    @staticmethod
    def _trial_posting_ids(db: Session):
        """Posting ids that may exercise UAT but must not enter empirical outputs."""
        return db.query(JobPosting.posting_id).filter(
            JobPosting.source.ilike("%TRIAL_NOT_EMPIRICAL%")
        )

    @staticmethod
    def _empirical_signal_query(db: Session):
        return db.query(LabourMarketSignal).filter(
            LabourMarketSignal.evidence_count > 0,
            LabourMarketSignal.confidence_score > 0,
            or_(
                LabourMarketSignal.signal_metadata["empirical_use_permitted"].astext.is_(None),
                LabourMarketSignal.signal_metadata["empirical_use_permitted"].astext != "false",
            ),
        )

    @staticmethod
    def _empirical_demand_query(db: Session):
        return db.query(SkillDemandEvidence).filter(
            or_(
                SkillDemandEvidence.evidence_metadata["empirical_use_permitted"].astext.is_(None),
                SkillDemandEvidence.evidence_metadata["empirical_use_permitted"].astext != "false",
            )
        )

    def readiness(self, db: Session) -> Dict[str, Any]:
        versions = db.query(CurriculumDocumentVersion).order_by(
            CurriculumDocumentVersion.created_at.desc()
        ).all()
        reviews = db.query(CurriculumEvidenceReview).order_by(
            CurriculumEvidenceReview.created_at.desc()
        ).all()
        latest_review = {}
        for review in reviews:
            latest_review.setdefault(review.version_id, review)

        eligible = []
        rejected = []
        for version in versions:
            review = latest_review.get(version.version_id)
            reasons = self.version_eligibility_reasons(version, review)
            item = {
                "version_id": str(version.version_id),
                "document_id": str(version.document_id),
                "content_hash": version.content_hash,
                "extracted_text_hash": version.extracted_text_hash,
                "review_id": str(review.review_id) if review else None,
                "reviewer_id": review.reviewer_id if review else None,
                "reasons": reasons,
            }
            (eligible if not reasons else rejected).append(item)

        approved_curriculum = db.query(SkillMapping).filter(
            SkillMapping.source_domain == "curriculum",
            SkillMapping.mapping_status == "approved",
        ).all()
        approved_labour = db.query(SkillMapping).filter(
            SkillMapping.source_domain == "labour_market",
            SkillMapping.mapping_status == "approved",
            ~SkillMapping.source_entity_id.in_(self._trial_posting_ids(db)),
        ).all()
        # Rejected mappings are completed governance decisions, not unfinished
        # work.  Only genuinely unresolved states may block regeneration.
        pending_mappings = db.query(SkillMapping).filter(
            SkillMapping.mapping_status.in_((
                "candidate",
                "needs_review",
                "disagreement",
                "deferred",
            )),
            or_(
                SkillMapping.source_domain != "labour_market",
                ~SkillMapping.source_entity_id.in_(self._trial_posting_ids(db)),
            ),
        ).count()
        signals = self._empirical_signal_query(db).all()
        demand_evidence = self._empirical_demand_query(db).all()

        checks = [
            self._check("validated_curriculum_versions", bool(eligible), len(eligible)),
            self._check("approved_curriculum_mappings", bool(approved_curriculum), len(approved_curriculum)),
            self._check("approved_labour_mappings", bool(approved_labour), len(approved_labour)),
            self._check("no_unresolved_mappings", pending_mappings == 0, pending_mappings),
            self._check("traceable_labour_signals", bool(signals), len(signals)),
            self._check("skill_demand_evidence", bool(demand_evidence), len(demand_evidence)),
        ]
        blocked = [check for check in checks if check["status"] == "blocked"]
        return {
            "status": "ready" if not blocked else "blocked",
            "checks": checks,
            "eligible_curriculum_versions": eligible,
            "rejected_curriculum_versions": rejected,
            "approved_curriculum_mapping_count": len(approved_curriculum),
            "approved_labour_mapping_count": len(approved_labour),
            "pending_mapping_count": pending_mappings,
            "labour_signal_count": len(signals),
            "skill_demand_evidence_count": len(demand_evidence),
        }

    def run(
        self,
        db: Session,
        actor_id: str | None,
        horizon_periods: int = 4,
    ) -> Dict[str, Any]:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtext('future_validated_regeneration'))"
            )
        )
        readiness = self.readiness(db)
        if readiness["status"] != "ready":
            failed = [item["key"] for item in readiness["checks"] if item["status"] == "blocked"]
            raise RuntimeError(f"Validated evidence regeneration is blocked: {failed}")

        input_manifest = self._input_manifest(db, readiness)
        before = self._output_ids(db)
        totals = {"alignments_created": 0, "forecasts_created": 0, "recommendations_created": 0}
        try:
            for version in readiness["eligible_curriculum_versions"]:
                alignment = analytics_recommendation_service.generate_alignment_scores(
                    db,
                    version_id=UUID(version["version_id"]),
                    commit=False,
                )
                recommendation = analytics_recommendation_service.generate_recommendations(
                    db,
                    version_id=UUID(version["version_id"]),
                    commit=False,
                )
                totals["alignments_created"] += int(alignment["alignments_created"])
                totals["recommendations_created"] += int(recommendation["recommendations_created"])
            forecast = analytics_recommendation_service.generate_forecasts(
                db,
                horizon_periods=horizon_periods,
                commit=False,
            )
            totals["forecasts_created"] = int(forecast["forecasts_created"])
            db.flush()
            after = self._output_ids(db)
            outputs = {
                key: sorted(after[key] - before[key])
                for key in before
            }
            manifest = {
                "schema_version": "validated_decision_outputs_v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": actor_id,
                "horizon_periods": horizon_periods,
                "inputs": input_manifest,
                "outputs": outputs,
                "output_counts": {key: len(value) for key, value in outputs.items()},
                "stage_totals": totals,
                "generation_policy": {
                    "curriculum": "latest expert review validated; authoritative and >=80% complete",
                    "skill_mappings": "approved only; zero unreviewed mappings globally",
                    "labour_signals": "positive evidence count and confidence",
                    "decision_authority": "outputs remain pending human review",
                },
            }
            manifest_hash = self._hash(manifest)
            report = GeneratedReport(
                report_type="validated_evidence_regeneration",
                source_entity_type="validated_evidence_manifest",
                source_entity_id=None,
                generated_by=actor_id,
                status="generated",
                title="Validated Evidence Decision Output Regeneration",
                summary={
                    "readiness_status": "ready",
                    "manifest_hash": manifest_hash,
                    "output_counts": manifest["output_counts"],
                    "stage_totals": totals,
                },
                payload=manifest,
                payload_hash=manifest_hash,
                format_hint="json",
                notes="Atomic regeneration from expert-validated and approved evidence only.",
            )
            db.add(report)
            db.commit()
            db.refresh(report)
            return {
                "status": "completed",
                "report_id": str(report.report_id),
                "manifest_hash": manifest_hash,
                "outputs": outputs,
                "output_counts": manifest["output_counts"],
                "stage_totals": totals,
            }
        except Exception:
            db.rollback()
            raise

    def latest_manifest(self, db: Session) -> Dict[str, Any] | None:
        report = db.query(GeneratedReport).filter(
            GeneratedReport.report_type == "validated_evidence_regeneration"
        ).order_by(GeneratedReport.created_at.desc()).first()
        if not report:
            return None
        return {
            "report_id": str(report.report_id),
            "status": report.status,
            "summary": report.summary,
            "payload_hash": report.payload_hash,
            "created_at": report.created_at,
        }

    def _input_manifest(self, db: Session, readiness: Dict[str, Any]) -> Dict[str, Any]:
        curriculum_mappings = db.query(SkillMapping).filter(
            SkillMapping.source_domain == "curriculum",
            SkillMapping.mapping_status == "approved",
        ).all()
        labour_mappings = db.query(SkillMapping).filter(
            SkillMapping.source_domain == "labour_market",
            SkillMapping.mapping_status == "approved",
            ~SkillMapping.source_entity_id.in_(self._trial_posting_ids(db)),
        ).all()
        signals = self._empirical_signal_query(db).all()
        demand = self._empirical_demand_query(db).all()
        return {
            "curriculum_versions": readiness["eligible_curriculum_versions"],
            "approved_curriculum_mapping_ids": sorted(str(row.mapping_id) for row in curriculum_mappings),
            "approved_labour_mapping_ids": sorted(str(row.mapping_id) for row in labour_mappings),
            "labour_signals": sorted(
                [{"signal_id": str(row.signal_id), "signal_hash": row.signal_hash} for row in signals],
                key=lambda row: row["signal_id"],
            ),
            "skill_demand_evidence": sorted(
                [{"evidence_id": str(row.evidence_id), "evidence_hash": row.evidence_hash} for row in demand],
                key=lambda row: row["evidence_id"],
            ),
        }

    @staticmethod
    def _output_ids(db: Session) -> Dict[str, set[str]]:
        return {
            "alignment_ids": {str(value) for (value,) in db.query(AlignmentScore.alignment_id).all()},
            "forecast_ids": {str(value) for (value,) in db.query(Forecast.forecast_id).all()},
            "recommendation_ids": {str(value) for (value,) in db.query(Recommendation.recommendation_id).all()},
        }

    @staticmethod
    def _check(key: str, passed: bool, count: int) -> Dict[str, Any]:
        return {"key": key, "status": "ready" if passed else "blocked", "count": int(count)}

    @staticmethod
    def version_eligibility_reasons(
        version: CurriculumDocumentVersion,
        review: CurriculumEvidenceReview | None,
    ) -> list[str]:
        reasons = []
        if version.extraction_status != "completed":
            reasons.append("extraction_not_completed")
        if not version.content_hash or not version.extracted_text_hash:
            reasons.append("missing_content_hash")
        if not review:
            reasons.append("no_expert_review")
            return reasons
        if review.decision != "validated":
            reasons.append(f"latest_review_{review.decision}")
        if not review.source_authoritative:
            reasons.append("source_not_authoritative")
        if not review.extraction_complete:
            reasons.append("review_extraction_incomplete")
        if not review.module_evidence_complete:
            reasons.append("module_evidence_incomplete")
        if not review.learning_outcomes_complete:
            reasons.append("learning_outcomes_incomplete")
        if int(review.completeness_score or 0) < 80:
            reasons.append("completeness_below_80")
        return reasons

    @staticmethod
    def _hash(payload: Dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


validated_regeneration_service = ValidatedRegenerationService()
