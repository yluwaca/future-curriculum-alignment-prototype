from types import SimpleNamespace

from app.services.reviewed_alignment_training_dataset_service import (
    reviewed_alignment_training_dataset_service,
)
from app.services.model_service import ModelService


def test_live_evidence_uses_reviewed_alignment_feature_builder():
    curriculum = SimpleNamespace(
        module_name="Data Analytics",
        description="Python SQL visualisation",
        faculty="Informatics",
        programme="Diploma ICT",
    )
    postings = [
        SimpleNamespace(
            job_title="Data analyst",
            job_description="Python and SQL",
            required_skills={"python": 1, "sql": 1},
            education_level="Diploma",
            experience_years=2,
            region="Western Cape",
            posted_date="2026-08-01",
        )
    ]

    features = reviewed_alignment_training_dataset_service.build_serving_features(
        curriculum, postings
    )

    assert set(features) == set(
        reviewed_alignment_training_dataset_service.build_features(
            {"curriculum_evidence": "", "labour_market_evidence": []}
        )
    )
    assert features["labour_evidence_record_count"] == 1.0
    assert features["shared_unique_token_count"] > 0


def test_candidate_operating_threshold_controls_served_classification():
    metrics = {
        "serving_feature_contract": {
            "contract_id": "reviewed_alignment_lexical_v1",
            "operating_threshold": 0.35,
        }
    }

    assert ModelService.classify_alignment_score(0.36, metrics) is True
    assert ModelService.classify_alignment_score(0.34, metrics) is False
