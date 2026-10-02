"""Tests for the S5 zero-evidence recommendation gate.

Handoff line 66: block creation or approval of recommendations whose evidence count
is zero; existing zero-evidence items must be marked non-actionable with a reason,
not silently deleted. Covers:

1. read-time actionability derivation (non-destructive, no rewrite of stored rows);
2. already-decided rows are not re-gated;
3. the review service blocks APPROVE on a zero-evidence recommendation (422);
4. the review service still allows REJECT on a zero-evidence recommendation;
5. generation-time metadata bakes the actionable flag + reason;
6. the recommendations list serializer derives actionability.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers.analytics import recommendation_actionability
from app.services.recommendation_review_service import recommendation_review_service

BACKEND = Path(__file__).parents[1]
ANALYTICS_ROUTER = BACKEND / "app" / "routers" / "analytics.py"
RECOMMENDATION_SERVICE = BACKEND / "app" / "services" / "analytics_recommendation_service.py"

ZERO_EV_META = {
    "evidence_status": "insufficient_evidence",
    "skill_demand_evidence_count": 0,
    "labour_evidence_count": 0,
    "top_demand_evidence": [],
}
SUPPORTED_META = {
    "evidence_status": "supported",
    "skill_demand_evidence_count": 4,
    "labour_evidence_count": 7,
    "top_demand_evidence": [{"evidence_id": "x"}],
}


def _fake_rec(status="pending_review", metadata=None):
    return SimpleNamespace(
        recommendation_id=uuid4(),
        status=status,
        recommendation_metadata=metadata if metadata is not None else {},
        confidence_score=0.5,
        title="Strengthen coverage",
        description="desc",
        priority="medium",
    )


# ------------------------------------------------- read-time actionability
def test_zero_evidence_pending_is_non_actionable_with_reason():
    rec = _fake_rec(status="pending_review", metadata=ZERO_EV_META)
    result = recommendation_actionability(rec)
    assert result["actionable"] is False
    assert "Zero resolvable labour-market evidence" in result["non_actionable_reason"]
    # non-destructive: the stored row is unchanged
    assert rec.status == "pending_review"
    assert rec.recommendation_metadata == ZERO_EV_META


def test_supported_recommendation_is_actionable():
    rec = _fake_rec(status="pending_review", metadata=SUPPORTED_META)
    result = recommendation_actionability(rec)
    assert result["actionable"] is True
    assert result["non_actionable_reason"] is None


def test_already_decided_zero_evidence_is_not_regated():
    # An approved/rejected row keeps its recorded outcome; the gate is for pending items.
    rec = _fake_rec(status="rejected", metadata=ZERO_EV_META)
    result = recommendation_actionability(rec)
    assert result["actionable"] is True
    assert result["non_actionable_reason"] is None


def test_zero_evidence_inferred_from_counts_without_explicit_status():
    rec = _fake_rec(
        status="pending_review",
        metadata={"skill_demand_evidence_count": 0, "labour_evidence_count": 0},
    )
    assert recommendation_actionability(rec)["actionable"] is False


# ------------------------------------------------- review-service gate
def test_approve_blocked_on_zero_evidence():
    rec = _fake_rec(status="pending_review", metadata=ZERO_EV_META)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = rec
    with pytest.raises(HTTPException) as exc:
        recommendation_review_service.review(
            db=db,
            recommendation_id=rec.recommendation_id,
            decision="approve",
            reviewer_id="curriculum_approver_01",
            reviewer_type="human",
            reason="Looks good",
        )
    assert exc.value.status_code == 422
    assert "Approval is blocked" in str(exc.value.detail)
    # the recommendation was NOT approved
    assert rec.status == "pending_review"


def test_reject_allowed_on_zero_evidence():
    rec = _fake_rec(status="pending_review", metadata=ZERO_EV_META)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = rec
    with patch("app.services.recommendation_review_service.log_audit_event"):
        result = recommendation_review_service.review(
            db=db,
            recommendation_id=rec.recommendation_id,
            decision="reject",
            reviewer_id="curriculum_approver_01",
            reviewer_type="human",
            reason="No labour-market evidence to support this recommendation",
        )
    assert rec.status == "rejected"
    assert result["recommendation"] is rec
    # the reject review recorded the non-actionable context
    assert result["review"].review_metadata.get("zero_evidence_non_actionable") is True


def test_approve_allowed_on_supported_evidence():
    rec = _fake_rec(status="pending_review", metadata=SUPPORTED_META)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = rec
    with patch("app.services.recommendation_review_service.log_audit_event"):
        recommendation_review_service.review(
            db=db,
            recommendation_id=rec.recommendation_id,
            decision="approve",
            reviewer_id="curriculum_approver_01",
            reviewer_type="human",
            reason="Evidence-backed and reviewed",
        )
    assert rec.status == "approved"


# ------------------------------------------------- source-level guarantees
def test_generation_bakes_actionable_flag():
    source = RECOMMENDATION_SERVICE.read_text(encoding="utf-8")
    assert '"actionable": not zero_evidence' in source
    assert '"non_actionable_reason"' in source


def test_list_serializer_derives_actionability():
    source = ANALYTICS_ROUTER.read_text(encoding="utf-8")
    assert "def recommendation_actionability(" in source
    assert "def _recommendation_response_dict(" in source
    assert "_recommendation_response_dict(row) for row in rows" in source
    # dossier surfaces the gate too
    assert '"actionable": actionability["actionable"]' in source
