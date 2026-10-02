"""Focused tests for the neutral Adzuna labour-market workflow UI.

The portal must support an end-to-end technical demonstration without
making policy, licensing, or research-use decisions in the interface.
These DB-free source-inspection tests guard the presentation layer while
the backend keeps the full technical metadata (source labels, acquisition
mode, empirical-use flag) intact.

Backend contract and live verification remain guarded by
test_labour_market_adzuna_pipeline.py and the UAT evidence document.
"""

from pathlib import Path

ROOT = Path(__file__).parents[2]
FRONTEND = ROOT / "frontend"


def read_frontend(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


BANNED_PHRASES = (
    "Technical UAT evidence",
    "Adzuna live trial",
    "live-trial ",
    "Trial warning",
    "Trial scope",
    "trial metadata",
    "empirical_use_permitted",
    "14-day",
    "coverage/quality/usability",
    "not eligible for empirical",
    "written consent",
    "licence is recorded",
    "live_trial_uat",
    "Current access: trial",
    "technical UAT only",
)


def test_forecast_panels_use_neutral_headings():
    for filename in ("dashboard.html", "data-operations.html", "system-operations.html"):
        html = read_frontend(filename)
        assert 'class="panel-head"><h3>Labour demand signals</h3>' in html
        assert "Generated from approved skill mappings on imported job-posting evidence" in html
        assert 'id="adzunaTrialOutlookPanel"' in html
        assert "No labour demand signals yet. Run the Labour-market Skill Pipeline, review mappings in Skills Alignment, then generate labour demand signals." in html


def test_no_policy_text_in_forecast_panels():
    for filename in ("dashboard.html", "data-operations.html", "system-operations.html"):
        html = read_frontend(filename)
        text = html.split('id="adzunaTrialOutlookPanel"')[0]
        for phrase in BANNED_PHRASES:
            assert phrase not in text, f"{filename} forecast panel contains banned phrase: {phrase!r}"


def test_pipeline_panel_neutral_and_functional():
    html = read_frontend("data-operations.html")
    pipeline_box_start = html.index("Labour-market Skill Pipeline")
    pipeline_box_end = html.index("Job Advert Dataset")
    box = html[pipeline_box_start:pipeline_box_end]
    assert "Run the labour-market skill pipeline on imported job-posting evidence, review skill mappings, and generate demand signals." in box
    assert 'id="adzunaPipelineSources" value="adzuna"' in html
    assert 'Run scope' in box and "stored postings only" in box
    for button in (
        "Run Labour-market Skill Pipeline",
        "Refresh status",
        "Review mappings in Skills Alignment",
        "Generate labour demand signals (approved mappings only)",
    ):
        assert button in box
    for phrase in BANNED_PHRASES:
        assert phrase not in box, f"pipeline panel contains banned phrase: {phrase!r}"


def test_adzuna_intake_text_neutral():
    html = read_frontend("data-operations.html")
    intake_box_start = html.index("<h4>Adzuna Live API</h4>")
    intake_box_end = html.index("<h4>Labour-market Skill Pipeline</h4>")
    box = html[intake_box_start:intake_box_end]
    assert "Import South African vacancies using the configured Adzuna account." in box
    assert "Current access" not in box
    for phrase in BANNED_PHRASES:
        assert phrase not in box


def test_viewer_facing_module_has_no_policy_text():
    module = read_frontend("adzuna-skill-pipeline.js")
    views = read_frontend("dashboard-views.js")
    user_visible = module + views
    # Every banned phrase must be gone from both the pipeline module and the
    # demand-signals renderer, wherever it would reach a user or the DOM.
    for phrase in BANNED_PHRASES:
        assert phrase not in user_visible, f"banned phrase still present: {phrase!r}"


def test_raw_source_label_never_rendered():
    """The internal source label may exist only as a mapping constant or
    comparison target, never as a rendered string."""
    expectation = {
        "adzuna-skill-pipeline.js": 2,  # SOURCE_TOKENS value + sourceNames compare
        "dashboard-views.js": 1,  # sourceLabelFor compare
        "dashboard-actions.js": 1,  # displaySourceLabel compare
    }
    for filename, expected_count in expectation.items():
        source = read_frontend(filename)
        assert source.count("ADZUNA_TRIAL_NOT_EMPIRICAL") == expected_count, filename


def test_review_link_enabled_when_mappings_exist():
    module = read_frontend("adzuna-skill-pipeline.js")
    update_review = _slice(module, "async function updateReviewLink", "async function runPipeline")
    assert "GOVERNANCE_WORKBENCH" in update_review
    assert "?limit=1" in update_review
    assert "mapping_status_summary" in update_review
    assert "[summary.approved, summary.candidate, summary.needs_review, summary.rejected]" in update_review
    assert "reviewLink.disabled = mappingCount <= 0" in update_review
    # An existing mapping set must enable the link even with no new mappings
    # created by the latest run, and the link must re-check on load and after
    # a run, a refresh, and signal generation.
    assert module.count("updateReviewLink()") >= 1
    assert "await updateReviewLink();" in module


def test_review_link_navigates_to_skills_alignment():
    module = read_frontend("adzuna-skill-pipeline.js")
    handler = _slice(module, "reviewLink.addEventListener", "refreshStatus();")
    assert "openDataOperationsSection('labour', 'review')" in handler
    assert "data-operations.html?area=labour&step=review" in handler


def test_pipeline_run_and_signal_generation_post_contract():
    module = read_frontend("adzuna-skill-pipeline.js")
    pipeline = _slice(module, "async function runPipeline", "async function generateSignals")
    signals = _slice(module, "async function generateSignals", "async function refreshStatus")
    assert "LABOUR_MARKET.SKILL_PIPELINE" in pipeline and "sources: sources()" in pipeline
    assert "LABOUR_MARKET.SKILL_PIPELINE_SIGNALS" in signals and "sources: sources()" in signals
    assert "SOURCE_TOKENS" in module and "{ adzuna: 'ADZUNA_TRIAL_NOT_EMPIRICAL' }" in module
    assert "['adzuna']" in module  # the neutral default token resolves to the real source


def test_demand_outlook_renders_signals_neutrally():
    views = read_frontend("dashboard-views.js")
    renderer = _slice(views, "async function renderAdzunaTrialOutlook", "export {")
    assert "SKILL_PIPELINE_TRIAL_SIGNALS" in renderer
    assert "no labour demand signals yet" in renderer.lower()
    assert "skill_name" in renderer and "evidence_count" in renderer and "unit" in renderer
    assert "empirical_use_permitted" not in renderer
    assert "sourceLabelFor" in renderer  # maps the internal label to 'Adzuna' at display time
    forecast = _slice(views, "function renderForecasts()", "export {")
    assert "renderAdzunaTrialOutlook();" in forecast


def test_signal_generation_is_stateful_and_idempotent_backend():
    service = (ROOT / "backend/app/services/labour_market_skill_pipeline_service.py").read_text(encoding="utf-8")
    clean = _slice(service, "def clean_job_postings", "def extract_and_map_job_skills")
    extract = _slice(service, "def extract_and_map_job_skills", "    @staticmethod")
    signals_fn = _slice(service, "def generate_job_skill_signals", "def generate_job_skill_demand_evidence")
    evidence = _slice(service, "def generate_job_skill_demand_evidence", "    @staticmethod")
    # Re-running the pipeline must not duplicate stored cleaners or mappings.
    assert "existing.content_hash == payload_hash" in clean and '"cleaned_skipped": skipped' in clean
    assert "mappings_skipped += 1" in extract and '"mappings_skipped": mappings_skipped' in extract
    # Re-running signal generation must update in place and skip duplicate
    # demand-evidence rows.
    assert "signals_updated" in signals_fn and "existing_hashes" in signals_fn
    assert "evidence_hash in existing_hashes" in evidence and "existing_hashes.add(evidence_hash)" in evidence
    assert '"evidence_skipped": skipped' in evidence


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]
