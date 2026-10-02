from types import SimpleNamespace

import pytest

from app.services.operational_job_service import OperationalJobService
from app.services.validated_regeneration_service import ValidatedRegenerationService


def test_curriculum_version_requires_complete_authoritative_expert_validation():
    service = ValidatedRegenerationService()
    version = SimpleNamespace(
        extraction_status="completed",
        content_hash="a" * 64,
        extracted_text_hash="b" * 64,
    )
    review = SimpleNamespace(
        decision="validated",
        source_authoritative=True,
        extraction_complete=True,
        module_evidence_complete=True,
        learning_outcomes_complete=True,
        completeness_score=90,
    )
    assert service.version_eligibility_reasons(version, review) == []

    review.learning_outcomes_complete = False
    review.completeness_score = 70
    assert service.version_eligibility_reasons(version, review) == [
        "learning_outcomes_incomplete",
        "completeness_below_80",
    ]


def test_missing_review_and_hashes_are_explicit_blockers():
    service = ValidatedRegenerationService()
    version = SimpleNamespace(
        extraction_status="pending",
        content_hash=None,
        extracted_text_hash=None,
    )
    reasons = service.version_eligibility_reasons(version, None)
    assert reasons == [
        "extraction_not_completed",
        "missing_content_hash",
        "no_expert_review",
    ]


def test_regeneration_stops_before_output_generation_when_readiness_is_blocked(monkeypatch):
    service = ValidatedRegenerationService()
    monkeypatch.setattr(
        service,
        "readiness",
        lambda db: {
            "status": "blocked",
            "checks": [
                {"key": "validated_curriculum_versions", "status": "blocked"}
            ],
        },
    )
    db = SimpleNamespace(execute=lambda statement: None)
    with pytest.raises(RuntimeError, match="validated_curriculum_versions"):
        service.run(db=db, actor_id="analyst")


def test_durable_worker_registers_validated_regeneration_handler():
    service = OperationalJobService()
    assert "processing.validated_regeneration" in service.handlers
