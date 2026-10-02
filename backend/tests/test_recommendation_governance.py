from pathlib import Path

from app.services.recommendation_governance_service import (
    COMMITTEE_DECISIONS,
    RecommendationGovernanceService,
)


def test_committee_decisions_are_human_workflow_states():
    assert COMMITTEE_DECISIONS == {
        "approve": "committee_approved",
        "approve_with_conditions": "committee_approved_with_conditions",
        "return_for_revision": "committee_revision_required",
        "reject": "committee_rejected",
        "defer": "committee_deferred",
    }


def test_payload_hash_is_stable_across_key_order():
    service = RecommendationGovernanceService()
    assert service._hash({"b": 2, "a": 1}) == service._hash({"a": 1, "b": 2})


def test_migration_enforces_append_only_decisions():
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "release4_recommendation_governance.py"
    ).read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "committee decisions are append-only" in migration
    assert "unique=True" in migration


def test_committee_api_is_role_restricted_and_separate_from_expert_review():
    router = (
        Path(__file__).parents[1] / "app" / "routers" / "analytics.py"
    ).read_text(encoding="utf-8")
    assert 'require_role("CURRICULUM_APPROVER")' in router
    assert 'require_permission("recommendation.academic_approve")' in router
    assert '"/recommendations/{recommendation_id}/committee-decision"' in router
    assert '"/recommendation-governance/committee-pack"' in router
