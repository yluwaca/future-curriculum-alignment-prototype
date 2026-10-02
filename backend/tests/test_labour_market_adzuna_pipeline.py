"""Focused tests for the Adzuna-to-demand-outlook skill pipeline workflow.

These verify the backend wiring on source inspection, matching the existing
DB-free pattern used by test_labour_mapping_promotion_gate.py. A live
functional verification is performed against example.internal and recorded in
docs/system_documentation/ADZUNA_TO_DEMAND_OUTLOOK_UAT_YYYY-MM-DD.md.
"""

from pathlib import Path

BACKEND_DIR = Path(__file__).parents[1]


def read(path: str) -> str:
    return (BACKEND_DIR / path).read_text(encoding="utf-8")


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


ROUTER = read("app/routers/labour_market.py")


def test_skill_pipeline_routes_require_analyst_role():
    pipeline = _slice(ROUTER, "def run_job_skill_pipeline", "def generate_job_skill_pipeline_signals")
    signals = _slice(ROUTER, "def generate_job_skill_pipeline_signals", "@router.get(\n    \"/jobs/skill-pipeline/runs\"")
    for body in (pipeline, signals):
        assert 'Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST"))' in body


def test_pipeline_service_run_accepts_sources_scope():
    service = read("app/services/labour_market_skill_pipeline_service.py")
    markers = {
        "def run(": "\n    def clean_job_postings(",
        "def clean_job_postings(": "\n    def extract_and_map_job_skills(",
        "def extract_and_map_job_skills(": "\n    def generate_job_skill_signals(",
        "def generate_job_skill_signals(": "\n    def generate_job_skill_demand_evidence(",
        "def generate_job_skill_demand_evidence(": "\n    @staticmethod",
    }
    for start_marker, end_marker in markers.items():
        body = _slice(service, start_marker, end_marker)
        assert "sources" in body, f"{start_marker} should accept a sources scope"


def test_signal_generation_approved_only_and_source_scoped():
    service = read("app/services/labour_market_skill_pipeline_service.py")
    signals = _slice(service, "def generate_job_skill_signals", "def generate_job_skill_demand_evidence")
    assert 'SkillMapping.mapping_status == "approved"' in signals
    assert '"promotion_gate": "approved_labour_mappings_only"' in signals
    assert "JobPosting.source.in_(list(sources))" in signals or "JobPosting.source.in_(source_list)" in signals
    evidence = _slice(service, "def generate_job_skill_demand_evidence", "    @staticmethod")
    assert "signal_metadata" in evidence and "source_counts" in evidence


def test_pipeline_route_writes_durable_run_and_audit():
    assert "from app.models.pipeline_run import PipelineRun" in ROUTER
    assert "def _persist_pipeline_run(" in ROUTER
    assert "PipelineRun(" in ROUTER
    assert "log_audit_event(" in ROUTER
    assert 'action="run_job_skill_pipeline"' in ROUTER


def test_pipeline_route_preserves_trial_scope_metadata():
    assert "ADZUNA_TRIAL_NOT_EMPIRICAL" in ROUTER
    assert "acquisition_mode" in ROUTER and 'live_trial_uat' in ROUTER
    assert "evidence_class" in ROUTER and "trial_uat" in ROUTER
    assert '"permission_status": permission["permission_status"]' in ROUTER
    assert '"permission_received_at": permission["permission_received_at"]' in ROUTER
    assert '"permission_scope": permission["permission_scope"]' in ROUTER
    assert '"empirical_use_permitted": True,' in ROUTER
    assert '"attribution_required": permission["attribution_required"]' in ROUTER
    assert '"attribution_url": permission["attribution_url"]' in ROUTER
    assert '"attribution_note": ADZUNA_ATTRIBUTION_NOTE,' in ROUTER
    assert '"evidence_path": permission["evidence_path"]' in ROUTER
    assert "ADZUNA_ATTRIBUTION_NOTE" in ROUTER


def test_signal_generation_route_schema_contract():
    schemas = read("app/schemas/labour_market.py")
    assert "class LabourMarketSkillSignalRequest(BaseModel):" in schemas
    assert "sources: Optional[List[str]]" in schemas
    for field in (
        "mappings_considered",
        "mappings_approved_used",
        "signals_created",
        "signals_updated",
        "evidence_created",
        "evidence_skipped",
        "trial_scope",
        "ingestion_job_ids",
        "run_id",
    ):
        assert field in schemas


def test_pipeline_response_returns_run_metadata():
    schemas = read("app/schemas/labour_market.py")
    for field in ("run_id", "sources", "ingestion_job_ids", "trial_scope"):
        assert field in _slice(schemas, "class LabourMarketSkillPipelineResponse", "class LabourMarketSkillSignalRequest")


def test_pipeline_runs_status_endpoint_visible_to_analyst():
    endpoint = _slice(ROUTER, "def list_skill_pipeline_runs", "@router.post(\n    \"/trends/normalise\"")
    assert 'pipeline_key.in_' in endpoint
    assert "scope_query(" in endpoint
    assert "ADZUNA_PIPELINE_RUN_KEY" in endpoint


def test_credential_fields_never_serialised_in_pipeline_routes():
    for secret in ("auth_config", "api_key", "ADZUNA_APP_KEY"):
        assert secret not in ROUTER
    schema = _slice(
        read("app/schemas/labour_market.py"),
        "class LabourMarketSkillSignalResponse",
        "class JobPostingResponse",
    )
    for secret in ("auth_config", "api_key", "api_key_header"):
        assert secret not in schema


def test_sources_filter_applied_before_limit_offset_window():
    """SQLAlchemy raises if .filter() is called after .limit()/.offset().

    Guard the query-build ordering in all service stages that accept a
    sources scope so the Adzuna-scoped pipeline does not regress to the
    InvalidRequestError seen on the live server.
    """
    service = read("app/services/labour_market_skill_pipeline_service.py")
    bounds = {
        "def clean_job_postings(": "\n    def extract_and_map_job_skills(",
        "def extract_and_map_job_skills(": "\n    @staticmethod",
        "def generate_job_skill_signals(": "\n    def generate_job_skill_demand_evidence(",
    }
    for start_marker, end_marker in bounds.items():
        body = _slice(service, start_marker, end_marker)
        assert "JobPosting.source.in_(list(sources))" in body
        filter_pos = body.index("JobPosting.source.in_(list(sources))")
        limit_pos = body.find(".limit(")
        assert limit_pos == -1 or filter_pos < limit_pos, (
            f"{start_marker} must apply the sources filter before .limit()/.offset()"
        )
        offset_pos = body.find(".offset(")
        assert offset_pos == -1 or filter_pos < offset_pos, (
            f"{start_marker} must apply the sources filter before .limit()/.offset()"
        )
