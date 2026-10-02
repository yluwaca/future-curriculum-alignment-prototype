"""Validated recommendation governance and committee evidence packs."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.generated_report import GeneratedReport
from app.models.recommendation import Recommendation
from app.models.recommendation_committee_decision import RecommendationCommitteeDecision
from app.models.recommendation_explanation import RecommendationExplanation
from app.models.recommendation_review import RecommendationReview
from app.models.recommendation_status_history import RecommendationStatusHistory
from app.services.audit_service import log_audit_event


COMMITTEE_DECISIONS = {
    "approve": "committee_approved",
    "approve_with_conditions": "committee_approved_with_conditions",
    "return_for_revision": "committee_revision_required",
    "reject": "committee_rejected",
    "defer": "committee_deferred",
}


class RecommendationGovernanceService:
    @staticmethod
    def _hash(payload: Any) -> str:
        encoded = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def latest_manifest(self, db: Session) -> GeneratedReport | None:
        return (
            db.query(GeneratedReport)
            .filter(GeneratedReport.report_type == "validated_evidence_regeneration")
            .order_by(GeneratedReport.created_at.desc())
            .first()
        )

    def readiness(self, db: Session) -> dict[str, Any]:
        manifest = self.latest_manifest(db)
        validated_ids = set((manifest.payload.get("outputs", {}) if manifest else {}).get("recommendation_ids", []))
        reviewed_ids = {
            str(value)
            for (value,) in db.query(RecommendationReview.recommendation_id).distinct().all()
        }
        explanation_ids = {
            str(value)
            for (value,) in db.query(RecommendationExplanation.recommendation_id).distinct().all()
        }
        eligible_ids = sorted(validated_ids & reviewed_ids & explanation_ids)
        checks = [
            {"key": "validated_regeneration_manifest", "status": "ready" if manifest else "blocked",
             "message": "A validated-evidence regeneration manifest must exist."},
            {"key": "validated_recommendations", "status": "ready" if validated_ids else "blocked",
             "message": "The manifest must contain newly generated recommendation IDs."},
            {"key": "documented_human_reviews", "status": "ready" if validated_ids & reviewed_ids else "blocked",
             "message": "At least one validated recommendation must have a documented human review."},
            {"key": "explanations", "status": "ready" if eligible_ids else "blocked",
             "message": "Reviewed recommendations must include supporting explanations."},
        ]
        ready = all(item["status"] == "ready" for item in checks)
        return {
            "status": "ready" if ready else "blocked",
            "checks": checks,
            "manifest_report_id": str(manifest.report_id) if manifest else None,
            "manifest_hash": manifest.payload_hash if manifest else None,
            "counts": {
                "validated_recommendations": len(validated_ids),
                "human_reviewed_validated": len(validated_ids & reviewed_ids),
                "committee_pack_eligible": len(eligible_ids),
            },
            "eligible_recommendation_ids": eligible_ids,
            "decision_authority": "A human committee retains final authority; no decision is automatic.",
        }

    def generate_pack(self, db: Session, actor_id: str) -> GeneratedReport:
        readiness = self.readiness(db)
        if readiness["status"] != "ready":
            blocked = [x["key"] for x in readiness["checks"] if x["status"] == "blocked"]
            raise HTTPException(status.HTTP_409_CONFLICT, detail={"message": "Committee pack is blocked.", "blocked_checks": blocked})

        recommendations = (
            db.query(Recommendation)
            .filter(Recommendation.recommendation_id.in_([UUID(x) for x in readiness["eligible_recommendation_ids"]]))
            .all()
        )
        items = []
        for recommendation in recommendations:
            reviews = db.query(RecommendationReview).filter(
                RecommendationReview.recommendation_id == recommendation.recommendation_id
            ).order_by(RecommendationReview.created_at.asc()).all()
            explanations = db.query(RecommendationExplanation).filter(
                RecommendationExplanation.recommendation_id == recommendation.recommendation_id
            ).all()
            items.append({
                "recommendation": jsonable_encoder(recommendation),
                "human_reviews": jsonable_encoder(reviews),
                "explanations": jsonable_encoder(explanations),
                "limitations": [
                    "Evidence supports deliberation and does not constitute an automatic curriculum decision.",
                    "Committee members must verify institutional context, feasibility, cost and policy constraints.",
                ],
            })
        payload = {
            "schema_version": "recommendation_committee_pack_v1",
            "source_manifest_report_id": readiness["manifest_report_id"],
            "source_manifest_hash": readiness["manifest_hash"],
            "recommendations": items,
            "governance": {
                "decision_authority": readiness["decision_authority"],
                "allowed_decisions": sorted(COMMITTEE_DECISIONS),
                "decision_records": "append-only",
            },
        }
        report = GeneratedReport(
            report_type="recommendation_committee_pack",
            source_entity_type="validated_evidence_manifest",
            source_entity_id=UUID(readiness["manifest_report_id"]),
            generated_by=actor_id,
            status="generated",
            title="Curriculum Recommendation Committee Evidence Pack",
            summary={"recommendation_count": len(items), "source_manifest_hash": readiness["manifest_hash"]},
            payload=payload,
            payload_hash=self._hash(payload),
            format_hint="json",
            notes="Committee-ready evidence snapshot; final decisions remain human.",
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return report

    def decide(
        self, db: Session, recommendation_id: UUID, evidence_report_id: UUID,
        actor_id: str, actor_type: str, decision: str, rationale: str,
        committee_name: str, meeting_reference: str, conditions: str | None,
    ) -> RecommendationCommitteeDecision:
        decision = decision.strip().lower()
        if decision not in COMMITTEE_DECISIONS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unsupported committee decision.")
        if len(rationale.strip()) < 10:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A meaningful committee rationale is required.")
        if decision == "approve_with_conditions" and not (conditions or "").strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Conditions are required for conditional approval.")
        recommendation = db.get(Recommendation, recommendation_id)
        report = db.get(GeneratedReport, evidence_report_id)
        if not recommendation or not report or report.report_type != "recommendation_committee_pack":
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recommendation or committee evidence pack not found.")
        pack_ids = {str(x["recommendation"]["recommendation_id"]) for x in report.payload.get("recommendations", [])}
        if str(recommendation_id) not in pack_ids:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Recommendation is not contained in this evidence pack.")
        if db.query(RecommendationCommitteeDecision).filter_by(recommendation_id=recommendation_id).first():
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A final committee decision already exists.")

        previous_status = recommendation.status
        recommendation.status = COMMITTEE_DECISIONS[decision]
        record = RecommendationCommitteeDecision(
            recommendation_id=recommendation_id, evidence_report_id=evidence_report_id,
            decided_by=actor_id, decision=decision, rationale=rationale.strip(),
            committee_name=committee_name.strip(), meeting_reference=meeting_reference.strip(),
            conditions=(conditions or "").strip() or None, evidence_hash=report.payload_hash,
            decision_metadata={"previous_status": previous_status, "new_status": recommendation.status},
        )
        db.add(record)
        db.add(RecommendationStatusHistory(
            recommendation_id=recommendation_id, changed_by=actor_id,
            previous_status=previous_status, new_status=recommendation.status,
            change_reason=rationale.strip(), transition_type="committee_decision",
            history_metadata={"evidence_report_id": str(evidence_report_id), "evidence_hash": report.payload_hash},
        ))
        log_audit_event(
            db=db, event_layer="application", event_type="committee_decision",
            actor_type=actor_type, actor_id=actor_id, token_id=None,
            source_component="recommendation.governance", action=decision, result="success",
            metadata={"recommendation_id": str(recommendation_id), "evidence_report_id": str(evidence_report_id)},
        )
        db.commit()
        db.refresh(record)
        return record


recommendation_governance_service = RecommendationGovernanceService()
