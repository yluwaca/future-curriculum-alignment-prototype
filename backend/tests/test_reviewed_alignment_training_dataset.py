from app.services.reviewed_alignment_training_dataset_service import (
    ReviewedAlignmentTrainingDatasetService,
)


def test_features_use_source_evidence_not_expert_review_fields():
    service = ReviewedAlignmentTrainingDatasetService()
    payload = {
        "curriculum_evidence": "Python programming data analysis database design",
        "labour_market_evidence": [
            {"title": "Data analyst", "skills": ["Python", "SQL", "visualisation"]}
        ],
        "final_alignment_label": 5,
        "labels": [
            {
                "alignment_label": 5,
                "confidence": 1.0,
                "justification": "This text must never become a feature",
                "present_skills": ["Python"],
                "missing_skills": ["Cloud"],
                "reviewer_id": "expert-a",
            }
        ],
    }
    original = service.build_features(payload)
    payload["final_alignment_label"] = 1
    payload["labels"][0]["alignment_label"] = 1
    payload["labels"][0]["justification"] = "Completely different label explanation"
    payload["labels"][0]["present_skills"] = ["Unrelated"]
    payload["labels"][0]["reviewer_id"] = "expert-b"
    assert service.build_features(payload) == original


def test_evidence_overlap_features_are_deterministic_and_bounded():
    service = ReviewedAlignmentTrainingDatasetService()
    features = service.build_features(
        {
            "curriculum_evidence": "Python SQL software engineering",
            "labour_market_evidence": [{"skills": ["python", "cloud", "sql"]}],
        }
    )
    assert features["shared_unique_token_count"] >= 2
    assert 0.0 <= features["vocabulary_jaccard"] <= 1.0
    assert 0.0 <= features["curriculum_vocabulary_coverage"] <= 1.0
    assert features == service.build_features(
        {
            "curriculum_evidence": "Python SQL software engineering",
            "labour_market_evidence": [{"skills": ["python", "cloud", "sql"]}],
        }
    )


def test_chronology_prefers_evidence_dates_and_has_stable_fallback():
    service = ReviewedAlignmentTrainingDatasetService()
    dated = service._chronology(
        {
            "labour_market_evidence": [
                {"period_end": "2026-03-31T00:00:00Z"},
                {"window_end": "2026 Q2"},
            ],
            "evidence_metadata": {"date": "2025-01-01"},
        },
        9,
    )
    fallback = service._chronology({"evidence_metadata": {"source": "approved"}}, 9)
    assert dated["dated"] is True
    assert dated["value"].startswith("2026-06-01")
    assert dated["source"] == "labour_market_evidence"
    assert dated["candidate_date_count"] == 2
    assert fallback == {
        "dated": False,
        "value": None,
        "sort_key": 9.0,
        "source": "locked_row_index_fallback",
        "source_key": None,
        "candidate_date_count": 0,
    }


def test_chronology_combines_numeric_labour_year_and_quarter():
    service = ReviewedAlignmentTrainingDatasetService()
    dated = service._chronology(
        {"labour_market_evidence": [{"year": 2025, "quarter": "Q4"}]},
        3,
    )
    assert dated["dated"] is True
    assert dated["value"].startswith("2025-12-01")
    assert dated["source"] == "labour_market_evidence"
    assert dated["source_key"] == "[0].year_quarter"
