from pathlib import Path


FRONTEND = Path(__file__).parents[2] / "frontend"


def test_decision_empty_states_explain_reason_action_and_non_inference():
    source = (FRONTEND / "dashboard-utils.js").read_text(encoding="utf-8")
    for key in ("recommendations", "skillMappings", "skillGaps", "forecasts", "governance", "reports"):
        assert f"{key}:" in source
    assert "<b>Why:</b>" in source
    assert "<b>Next step:</b>" in source
    assert "<b>Do not infer:</b>" in source


def test_filter_empty_states_are_distinct_from_missing_evidence():
    source = (FRONTEND / "dashboard-views.js").read_text(encoding="utf-8")
    assert "No recommendations match this filter" in source
    assert "decisionEmptyState('recommendations')" in source
    assert "No forecasts match this filter" in source
    assert "decisionEmptyState('forecasts')" in source


def test_recommendation_review_page_warns_against_automatic_decisions():
    html = (FRONTEND / "recommendations.html").read_text(encoding="utf-8")
    script = (FRONTEND / "recommendations.js").read_text(encoding="utf-8")
    assert "Decision-support limitation" in html
    assert "They do not automatically establish" in html
    assert "Never approve or reject a recommendation without its evidence dossier." in script
    assert "An empty list does not mean the curriculum has no gaps" in script


def test_gap_and_forecast_outputs_have_visible_limitations():
    html = (FRONTEND / "dashboard.html").read_text(encoding="utf-8")
    assert "A gap is a difference between available curriculum and labour-market evidence." in html
    assert "never treat a projection as a guaranteed outcome." in html

def test_executive_renderer_defines_decision_audience_before_use():
    source = (FRONTEND / "dashboard-views.js").read_text(encoding="utf-8")
    render_executive = source.split("function renderExecutive()", 1)[1].split("function renderCurriculum()", 1)[0]
    declaration = "const isDecisionAudience = isViewer || document.body.classList.contains('analyst-audience');"
    assert declaration in render_executive
    assert render_executive.index(declaration) < render_executive.index("if (isDecisionAudience")

