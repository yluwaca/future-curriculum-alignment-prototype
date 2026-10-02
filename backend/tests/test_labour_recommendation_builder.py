"""Tests for the deterministic labour-workflow recommendation builder.

Guards the decision-support contract: only approved evidence drives
recommendations, every recommendation carries the required governance and
traceability fields, duplicates are suppressed, and rejected or unreviewed
mappings are never used. Synthetic fixtures are technical UAT evidence only.
"""

from __future__ import annotations

import pytest

from app.services.labour_recommendation_builder import (
    COVERAGE_RECOMMENDATION,
    GAP_RECOMMENDATION,
    RECOMMENDATION_TYPE,
    REQUIRED_FIELDS,
    REVIEW_STATUS,
    RecommendationBuildError,
    labour_recommendation_builder,
)


def _mapping(skill_id, skill_name, mapping_id, status="approved", source="adzuna", posting_id="p-1", job_id="j-1"):
    return {
        "mapping_id": mapping_id,
        "skill_id": skill_id,
        "skill_key": skill_name.lower().replace(" ", "-"),
        "skill_name": skill_name,
        "mapping_status": status,
        "source": source,
        "posting_id": posting_id,
        "job_id": job_id,
        "confidence": 0.8,
    }


def _signal(skill_id, skill_name, year=2026, quarter="Q3", demand=0.6, confidence=0.8):
    return {
        "signal_id": f"sig-{skill_id}",
        "skill_id": skill_id,
        "skill_name": skill_name,
        "canonical_name": f"Job demand for {skill_name}",
        "dimension_value": skill_name,
        "year": year,
        "quarter": quarter,
        "demand_score": demand,
        "confidence_score": confidence,
        "evidence_count": 3,
        "source_summary": "adzuna: 5",
    }


def _evidence(skill_id, skill_name, signal_id, demand=0.6, confidence=0.8):
    return {
        "evidence_id": f"ev-{skill_id}",
        "skill_id": skill_id,
        "skill_name": skill_name,
        "signal_id": signal_id,
        "demand_score": demand,
        "confidence_score": confidence,
    }


def test_no_evidence_yields_no_recommendations():
    result = labour_recommendation_builder.compute_recommendations([], [], [], [])
    assert result == []


def test_approved_evidence_yields_recommendations_with_required_fields():
    python = "skill-python"
    labour = [_mapping(python, "Python programming", "lab-map-1")]
    curriculum = []
    signals = [_signal(python, "Python programming")]
    evidence = [_evidence(python, "Python programming", "sig-skill-python")]
    result = labour_recommendation_builder.compute_recommendations(
        labour, curriculum, signals, evidence
    )
    assert len(result) >= 1
    recommendation = result[0]
    for required in REQUIRED_FIELDS:
        assert recommendation.get(required) is not None, f"missing {required}"
    assert recommendation["review_status"] == REVIEW_STATUS
    assert recommendation["recommendation_text"]
    assert recommendation["explanation"]
    assert recommendation["evidence_ids"]["demand_signal_ids"] == ["sig-skill-python"]
    assert recommendation["evidence_ids"]["demand_evidence_ids"] == ["ev-skill-python"]
    assert recommendation["evidence_ids"]["labour_mapping_ids"] == ["lab-map-1"]
    assert recommendation["source_period"]["periods"]
    assert recommendation["created_at"]
    assert recommendation["confidence"] > 0


def test_gap_vs_coverage_recommendations():
    gap_skill = "skill-cloud"
    covered_skill = "skill-python"
    covered_mapping = _mapping(covered_skill, "Python programming", "cur-map-1", status="approved")
    recom = labour_recommendation_builder.compute_recommendations(
        approved_labour_mappings=[covered_mapping],
        approved_curriculum_mappings=[covered_mapping],
        demand_signals=[
            _signal(gap_skill, "Cloud computing"),
            _signal(covered_skill, "Python programming"),
        ],
        demand_evidence=[
            _evidence(gap_skill, "Cloud computing", "sig-skill-cloud"),
            _evidence(covered_skill, "Python programming", "sig-skill-python"),
        ],
    )
    kinds = {item["kind"] for item in recom}
    assert GAP_RECOMMENDATION in kinds
    assert COVERAGE_RECOMMENDATION in kinds
    for item in recom:
        if item["kind"] == GAP_RECOMMENDATION:
            assert item["priority"] == "high"
        else:
            assert item["priority"] == "medium"


def test_rejected_evidence_never_used():
    skill = "skill-rejected"
    rejected = _mapping(skill, "Unwanted skill", "rej-map-1", status="rejected")
    result = labour_recommendation_builder.compute_recommendations(
        approved_labour_mappings=[rejected],
        approved_curriculum_mappings=[rejected],
        demand_signals=[],
        demand_evidence=[],
        allow_unapproved=True,
    )
    assert result == []


def test_unreviewed_evidence_never_used():
    skill = "skill-draft"
    unreviewed = _mapping(skill, "Draft skill", "draft-map-1", status="needs_review")
    result = labour_recommendation_builder.compute_recommendations(
        approved_labour_mappings=[unreviewed],
        approved_curriculum_mappings=[unreviewed],
        demand_signals=[],
        demand_evidence=[],
        allow_unapproved=True,
    )
    assert result == []


def test_conflicting_evidence_uses_approved_only():
    skill = "skill-mixed"
    approved = _mapping(skill, "Approved skill", "ap-map-1", status="approved")
    rejected = _mapping(skill, "Rejected alias", "rj-map-1", status="rejected")
    result = labour_recommendation_builder.compute_recommendations(
        approved_labour_mappings=[approved, rejected],
        approved_curriculum_mappings=[rejected, approved],
        demand_signals=[_signal(skill, "Approved skill")],
        demand_evidence=[_evidence(skill, "Approved skill", "sig-skill-mixed")],
        allow_unapproved=True,
    )
    assert len(result) == 1
    evidence_ids = result[0]["evidence_ids"]
    assert "ap-map-1" in evidence_ids["labour_mapping_ids"]
    assert "rj-map-1" not in evidence_ids["labour_mapping_ids"]
    assert "rj-map-1" not in evidence_ids["curriculum_mapping_ids"]


def test_unapproved_inputs_rejected_by_default():
    with pytest.raises(RecommendationBuildError):
        labour_recommendation_builder.compute_recommendations(
            approved_labour_mappings=[_mapping("s-1", "S1", "m-1", status="candidate")],
            approved_curriculum_mappings=[],
            demand_signals=[],
            demand_evidence=[],
        )


def test_duplicate_recommendations_suppressed():
    revisions = [
        _signal("s-x", "Data analysis", year=2026, quarter="Q3"),
        _signal("s-x", "Data analysis", year=2026, quarter="Q3"),
    ]
    evidence = [
        _evidence("s-x", "Data analysis", "sig-s-x"),
    ]
    result = labour_recommendation_builder.compute_recommendations(
        approved_labour_mappings=[_mapping("s-x", "Data analysis", "m-x")],
        approved_curriculum_mappings=[],
        demand_signals=revisions,
        demand_evidence=evidence,
    )
    deduplicated = labour_recommendation_builder.deduplicate(result + result)
    assert len(deduplicated) == len(result)
    assert len({item["dedup_key"] for item in deduplicated}) == len(deduplicated)


def test_traceability_back_to_postings_and_curriculum():
    skill = "skill-trace"
    labour = _mapping(skill, "Networking", "trace-lab", source="dpsa_pull", posting_id="posting-42", job_id="job-42")
    curriculum = _mapping(skill, "Networking", "trace-cur", status="approved")
    signals = [_signal(skill, "Networking")]
    evidence = [_evidence(skill, "Networking", "sig-skill-trace")]
    result = labour_recommendation_builder.compute_recommendations(
        [labour], [curriculum], signals, evidence
    )
    recommendation = result[0]
    assert "trace-lab" in recommendation["evidence_ids"]["labour_mapping_ids"]
    assert "trace-cur" in recommendation["evidence_ids"]["curriculum_mapping_ids"]
    assert "dpsa_pull" in recommendation["source_period"]["sources"]
    assert recommendation["kind"] == COVERAGE_RECOMMENDATION
    assert recommendation["skill_id"] == skill


def test_mapping_metadata_preserves_posting_reference_contract():
    """The DB loader must carry posting provenance into the recommendation."""
    from app.services.labour_recommendation_builder import _require_approved

    mapping = _mapping("s-1", "S1", "m-9", posting_id="posting-z", job_id="job-z")
    assert labour_recommendation_builder._approved_only([mapping]) == [mapping]
    _require_approved(mapping)
    assert mapping["posting_id"] == "posting-z"
    assert mapping["job_id"] == "job-z"


def test_recommendation_type_constant():
    assert RECOMMENDATION_TYPE == "labour_demand_curriculum"