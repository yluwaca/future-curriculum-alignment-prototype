"""
Human-in-the-loop recommendation review workflow.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.models.recommendation import Recommendation
from app.models.recommendation_feedback import RecommendationFeedback
from app.models.recommendation_review import RecommendationReview
from app.models.recommendation_status_history import RecommendationStatusHistory
from app.services.audit_service import log_audit_event


DECISION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "modify": "modified_pending_review",
}

ALLOWED_REVIEW_PRIORITIES = {"high", "medium", "low"}

_ROLE_LABELS = {
    "curriculum_approver": "Curriculum Approver",
    "admin": "Administrator",
    "analyst": "Analyst",
    "data_scientist": "Data Scientist",
    "viewer": "Viewer",
}


def _primary_role(roles: List[str]) -> Optional[str]:
    """Return the most decision-relevant role label from a reviewer's role ids."""
    if not roles:
        return None
    lowered = [role.lower() for role in roles]
    for key in ("curriculum_approver", "admin", "data_scientist", "analyst", "viewer"):
        if key in lowered:
            return _ROLE_LABELS[key]
    return roles[0]


class RecommendationReviewService:
    """
    Applies reviewer decisions and records governance evidence.
    """

    def review(
        self,
        db: Session,
        recommendation_id: UUID,
        decision: str,
        reviewer_id: str,
        reviewer_type: str,
        reason: Optional[str] = None,
        feedback_comment: Optional[str] = None,
        feedback_rating: Optional[float] = None,
        modified_title: Optional[str] = None,
        modified_description: Optional[str] = None,
        modified_priority: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        evidence_context: Optional[Dict[str, Any]] = None,
        evidence_reviewed: Optional[bool] = None,
        submitted_recommendation_id: Optional[UUID] = None,
        submitted_decision: Optional[str] = None,
        reviewer_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalised_decision = decision.lower().strip()

        if normalised_decision not in DECISION_TO_STATUS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="decision must be approve, reject, or modify",
            )

        recommendation = (
            db.query(Recommendation)
            .filter(Recommendation.recommendation_id == recommendation_id)
            .first()
        )

        if not recommendation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recommendation not found",
            )

        previous_status = recommendation.status
        new_status = DECISION_TO_STATUS[normalised_decision]
        review_metadata = metadata or {}

        # Zero-evidence gate (handoff S5): a recommendation with no resolvable
        # labour-market evidence can never be APPROVED. Approval requires an
        # evidence-backed recommendation; a zero-evidence item must first be
        # re-supported by demand-evidence generation. Rejection stays allowed so a
        # reviewer can explicitly dismiss it, and the item is marked non-actionable
        # with a reason rather than silently deleted (append-only governance).
        rec_meta = recommendation.recommendation_metadata or {}
        evidence_status = rec_meta.get("evidence_status")
        demand_count = rec_meta.get("skill_demand_evidence_count")
        labour_count = rec_meta.get("labour_evidence_count")
        zero_evidence = evidence_status == "insufficient_evidence" or (
            not demand_count and not labour_count and not rec_meta.get("top_demand_evidence")
        )
        if zero_evidence and normalised_decision == "approve":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Approval is blocked: this recommendation has zero resolvable "
                    "labour-market evidence (evidence_status=insufficient_evidence; "
                    f"skill_demand_evidence_count={demand_count or 0}, "
                    f"labour_evidence_count={labour_count or 0}). Re-run demand-evidence "
                    "generation to support it, or reject it. It remains marked "
                    "non-actionable and is never silently deleted."
                ),
            )
        if zero_evidence:
            review_metadata["zero_evidence_non_actionable"] = True
            review_metadata["zero_evidence_reason"] = (
                "No labour-market source records, demand rows, or canonical signals "
                "resolved for this skill; non-actionable for approval until re-supported."
            )

        if submitted_recommendation_id is None:
            submitted_recommendation_id = recommendation.recommendation_id
        if str(submitted_recommendation_id) != str(recommendation.recommendation_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="recommendation_id in the request does not match the reviewed recommendation",
            )
        if submitted_decision is not None and str(submitted_decision).strip().lower() != normalised_decision:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="decision in the request does not match the review endpoint",
            )
        review_metadata["reviewed_recommendation_id"] = str(recommendation.recommendation_id)
        if submitted_decision is not None:
            review_metadata["submitted_decision"] = str(submitted_decision).strip().lower()
        if evidence_context is not None:
            review_metadata["evidence_context"] = jsonable_encoder(evidence_context)
        if "evidence_reviewed" not in review_metadata:
            review_metadata["evidence_reviewed"] = bool(evidence_reviewed)

        # Persist the reviewer's role(s) so the portal audit view can show *who* acted
        # in what capacity (the role is otherwise not inferable from a decided row).
        normalised_roles = sorted({str(r).strip() for r in (reviewer_roles or []) if str(r).strip()})
        review_metadata["reviewer_roles"] = normalised_roles
        review_metadata["reviewer_role"] = _primary_role(normalised_roles)

        # Deterministic evidence-context fingerprint: binds this persisted review to the
        # exact recommendation, decision, reviewer, role and evidence context that were
        # acted on. Recomputed nowhere else, so it is an auditable identity for the row.
        fingerprint_payload = {
            "recommendation_id": str(recommendation.recommendation_id),
            "decision": normalised_decision,
            "previous_status": previous_status,
            "new_status": new_status,
            "reviewer_id": reviewer_id,
            "reviewer_roles": normalised_roles,
            "evidence_reviewed": bool(review_metadata.get("evidence_reviewed")),
            "evidence_context": review_metadata.get("evidence_context"),
        }
        review_metadata["evidence_context_fingerprint"] = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        reason = (reason or "").strip() or None
        feedback_comment = (feedback_comment or "").strip() or None
        modified_title = (modified_title or "").strip() or None
        modified_description = (modified_description or "").strip() or None
        modified_priority = modified_priority.strip().lower() if modified_priority else None
        if modified_priority is not None and modified_priority not in ALLOWED_REVIEW_PRIORITIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="modified_priority must be one of: high, medium, low",
            )

        if normalised_decision == "modify":
            if modified_title:
                recommendation.title = modified_title
            if modified_description:
                recommendation.description = modified_description
            if modified_priority:
                recommendation.priority = modified_priority
            review_metadata["modified_fields"] = {
                "title": bool(modified_title),
                "description": bool(modified_description),
                "priority": bool(modified_priority),
            }

        recommendation.status = new_status

        review = RecommendationReview(
            recommendation_id=recommendation.recommendation_id,
            reviewer_id=reviewer_id,
            decision=normalised_decision,
            previous_status=previous_status,
            new_status=new_status,
            decision_reason=reason,
            confidence_score=recommendation.confidence_score,
            modified_title=modified_title,
            modified_description=modified_description,
            modified_priority=modified_priority,
            review_metadata=review_metadata,
        )
        db.add(review)
        db.flush()

        history = RecommendationStatusHistory(
            recommendation_id=recommendation.recommendation_id,
            changed_by=reviewer_id,
            previous_status=previous_status,
            new_status=new_status,
            change_reason=reason,
            transition_type=f"review_{normalised_decision}",
            history_metadata={
                "review_id": str(review.review_id),
                "decision": normalised_decision,
            },
        )
        db.add(history)

        feedback = None
        if feedback_comment:
            feedback = RecommendationFeedback(
                recommendation_id=recommendation.recommendation_id,
                review_id=review.review_id,
                reviewer_id=reviewer_id,
                feedback_type=f"{normalised_decision}_feedback",
                rating=feedback_rating,
                comment=feedback_comment,
                feedback_metadata={
                    "decision": normalised_decision,
                    "previous_status": previous_status,
                    "new_status": new_status,
                },
            )
            db.add(feedback)

        log_audit_event(
            db=db,
            event_layer="application",
            event_type="recommendation_review",
            actor_type=reviewer_type,
            actor_id=reviewer_id,
            token_id=None,
            source_component="recommendation.review",
            action=f"recommendation_{normalised_decision}",
            result="success",
            metadata={
                "recommendation_id": str(recommendation.recommendation_id),
                "review_id": str(review.review_id),
                "previous_status": previous_status,
                "new_status": new_status,
                "has_feedback": feedback is not None,
            },
        )

        db.commit()
        db.refresh(recommendation)
        db.refresh(review)

        return {
            "recommendation": recommendation,
            "review": review,
            "history": history,
            "feedback": feedback,
        }


recommendation_review_service = RecommendationReviewService()
