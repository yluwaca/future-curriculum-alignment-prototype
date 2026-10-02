from app.services.analytics_recommendation_service import AnalyticsRecommendationService


def test_gap_classification_missing():
    assert AnalyticsRecommendationService.classify_skill_alignment(0, 12) == ("missing", 0.0)


def test_gap_classification_weak():
    gap_type, coverage = AnalyticsRecommendationService.classify_skill_alignment(2, 10)
    assert gap_type == "weak_alignment"
    assert coverage == 0.2


def test_gap_classification_aligned_at_threshold():
    gap_type, coverage = AnalyticsRecommendationService.classify_skill_alignment(3, 10)
    assert gap_type == "aligned"
    assert coverage == 0.3


def test_gap_classification_handles_no_labour_denominator():
    gap_type, coverage = AnalyticsRecommendationService.classify_skill_alignment(1, 0)
    assert gap_type == "aligned"
    assert coverage == 1.0
