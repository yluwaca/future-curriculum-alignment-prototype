"""Tests for the recommendation review submission contract (backend).

Confirms the service still preserves the full human-review audit trail
(recommendation_review, recommendation_status_history, audit event) while
field-level validation errors are produced by the request schema so the UI can
expose them.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.analytics import RecommendationReviewRequest
from app.services.recommendation_review_service import (
    DECISION_TO_STATUS,
    recommendation_review_service,
)

SERVICE_SOURCE = Path(
    __file__,
).parents[1] / "app" / "services" / "recommendation_review_service.py"


def test_decision_to_status_mapping_is_stable():
    assert DECISION_TO_STATUS == {
        "approve": "approved",
        "reject": "rejected",
        "modify": "modified_pending_review",
    }


def test_review_service_preserves_audit_trail():
    source = SERVICE_SOURCE.read_text(encoding="utf-8")
    # The immutable review row and the status transition history.
    assert "RecommendationReview(" in source
    assert "RecommendationStatusHistory(" in source
    assert 'transition_type=f"review_{normalised_decision}"' in source
    # A loggable audit event accompanies every decision.
    assert "log_audit_event(" in source
    assert 'event_type="recommendation_review"' in source
    assert 'result="success"' in source
    # The transaction is committed atomically with the audit record.
    assert "db.commit()" in source


def test_review_service_normalises_and_validates_inputs():
    source = SERVICE_SOURCE.read_text(encoding="utf-8")
    # The service strips free-text fields and validates modified_priority so
    # invalid values never reach the immutable review row.
    assert 'reason = (reason or "").strip() or None' in source
    assert 'modified_priority.strip().lower() if modified_priority else None' in source
    assert "ALLOWED_REVIEW_PRIORITIES" in source


def test_review_service_rejects_unknown_decision_before_db_access():
    with pytest.raises(HTTPException) as exc:
        recommendation_review_service.review(
            db=None,
            recommendation_id="00000000-0000-0000-0000-000000000000",
            decision="maybe",
            reviewer_id="reviewer-1",
            reviewer_type="human",
        )
    assert exc.value.status_code == 422
    assert "approve, reject, or modify" in str(exc.value.detail)


def test_request_schema_normalises_text_fields_and_empties_to_none():
    request = RecommendationReviewRequest(
        reason="  Senior lecturer evidence reviewed  ",
        feedback_comment="   ",
        modified_title=" Strengthen ML in year 4 ",
        modified_priority="HIGH",
    )
    assert request.reason == "Senior lecturer evidence reviewed"
    assert request.feedback_comment is None
    assert request.modified_title == "Strengthen ML in year 4"
    assert request.modified_priority == "high"
    assert request.metadata == {}


def test_request_schema_accepts_review_traceability_fields():
    request = RecommendationReviewRequest(
        recommendation_id="11111111-2222-3333-4444-555555555555",
        decision="APPROVE",
        evidence_reviewed=True,
        evidence_context={"skill_name": "ML", "gap_type": "EMERGING", "demand_score": 0.9},
    )
    assert str(request.recommendation_id) == "11111111-2222-3333-4444-555555555555"
    assert request.decision == "approve"
    assert request.evidence_reviewed is True
    assert request.evidence_context == {"skill_name": "ML", "gap_type": "EMERGING", "demand_score": 0.9}


def test_request_schema_rejects_invalid_decision_value():
    with pytest.raises(ValidationError) as exc:
        RecommendationReviewRequest(decision="assign")
    assert exc.value.errors()[0]["loc"][-1] == "decision"
    assert "approve, reject, modify" in exc.value.errors()[0]["msg"]


def test_review_service_stores_evidence_reviewed_and_decision_offset_in_metadata():
    source = SERVICE_SOURCE.read_text(encoding="utf-8")
    # The immutable review row records that evidence context was viewed, which
    # recommendation the request claimed, and that the decision matched.
    assert 'review_metadata["reviewed_recommendation_id"] = str(recommendation.recommendation_id)' in source
    assert 'review_metadata["evidence_reviewed"] = bool(evidence_reviewed)' in source
    assert 'review_metadata["evidence_context"] = jsonable_encoder(evidence_context)' in source
    assert "jsonable_encoder" in source
    # A mismatched recommendation/decision is rejected before persistence.
    assert "recommendation_id in the request does not match the reviewed recommendation" in source
    assert "decision in the request does not match the review endpoint" in source


def test_request_schema_returns_field_level_validation_errors():
    with pytest.raises(ValidationError) as exc:
        RecommendationReviewRequest(modified_priority="urgent")
    error = exc.value.errors()[0]
    assert error["loc"][-1] == "modified_priority"
    assert "must be one of: high, medium, low" in error["msg"]

    with pytest.raises(ValidationError) as exc:
        RecommendationReviewRequest(modified_title="x" * 256)
    assert exc.value.errors()[0]["loc"][-1] == "modified_title"
    assert "255" in exc.value.errors()[0]["msg"]

    with pytest.raises(ValidationError) as exc:
        RecommendationReviewRequest(feedback_rating=7.0)
    assert exc.value.errors()[0]["loc"][-1] == "feedback_rating"