"""Regression tests for the Adzuna academic research permission update.

DB-free source-inspection guards (matching the existing project test style)
verify that the written academic permission metadata (received 2026-09-10)
travels through the source register, ingestion runs, skill-pipeline signals,
demand evidence and report exports, while the stable source identity and
pagination/duplicate/rate-limit safeguards are preserved so historical
records remain auditable and re-imports stay idempotent.
"""

from pathlib import Path

import pytest


def _find_backend() -> Path:
    """Locate the backend app tree in either the repo layout (repo/backend)
    or the deployed container layout (/app)."""
    start = Path(__file__).resolve()
    for ancestor in (start, *start.parents):
        for backend in (ancestor, ancestor / "backend"):
            if (
                backend / "app" / "services" / "ingestion" / "adzuna_governance.py"
            ).is_file():
                return backend
    return start.parent


def _find_frontend(backend: Path) -> Path:
    frontend = backend.parent / "frontend"
    if frontend.is_dir():
        return frontend
    return backend / "frontend"


BACKEND = _find_backend()
FRONTEND = _find_frontend(BACKEND)
HAS_FRONTEND = FRONTEND.is_dir()
HAS_EVIDENCE = (
    BACKEND.parent / "docs" / "evidence" / "adzuna-permission-2026-09-10.md"
).is_file()

EVIDENCE_ONLY = pytest.mark.skipif(
    not HAS_EVIDENCE,
    reason="evidence tree not present in this layout",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


IMPORTER = read(BACKEND / "app/services/ingestion/adzuna_paginated_importer.py")
CONNECTOR = read(BACKEND / "app/services/ingestion/job_board_api_connector.py")
GOVERNANCE = read(BACKEND / "app/services/ingestion/adzuna_governance.py")
ROUTER = read(BACKEND / "app/routers/labour_market.py")
ANALYTICS = read(BACKEND / "app/routers/analytics.py")
PIPELINE = read(BACKEND / "app/services/labour_market_skill_pipeline_service.py")
SCHEMA = read(BACKEND / "app/schemas/labour_market.py")

HELP_MANUAL = read(FRONTEND / "help-manual.html") if HAS_FRONTEND else ""
DATA_OPS = read(FRONTEND / "data-operations.html") if HAS_FRONTEND else ""
DASHBOARD = read(FRONTEND / "dashboard.html") if HAS_FRONTEND else ""
VIEWS = read(FRONTEND / "dashboard-views.js") if HAS_FRONTEND else ""
ACTIONS = read(FRONTEND / "dashboard-actions.js") if HAS_FRONTEND else ""
EVIDENCE = (
    read(BACKEND.parent / "docs/evidence/adzuna-permission-2026-09-10.md")
    if HAS_EVIDENCE
    else ""
)

# The container bundles a pre-permission copy of the frontend; the wording
# regressions are meaningful only against a copy that carries the update.
HAS_PERMISSION_FRONTEND = "written academic research permission" in HELP_MANUAL

BACKEND_ONLY = pytest.mark.skipif(
    not HAS_FRONTEND or not HAS_PERMISSION_FRONTEND,
    reason="frontend tree absent or a pre-permission copy in this layout",
)

PERMISSION_MARKERS = (
    "permission_status",
    "written_academic_permission",
    "permission_received_at",
    "2026-09-10",
    "empirical_use_permitted",
    "attribution_required",
    "attribution_url",
    "https://www.adzuna.co.za",
)


def test_permission_metadata_shared_module():
    for marker in PERMISSION_MARKERS:
        assert marker in GOVERNANCE
    assert "ADZUNA_ATTRIBUTION_NOTE = (" in GOVERNANCE
    assert "def apply_adzuna_permission(source" in GOVERNANCE
    assert "source.is_authorised = True" in GOVERNANCE


def test_importer_and_connector_use_approved_permission():
    for module in (IMPORTER, CONNECTOR):
        assert "apply_adzuna_permission" in module
        assert "attribution_note" in module
    assert "ADZUNA_PERMISSION[\"empirical_use_permitted\"]" in IMPORTER
    assert '"permission_status": permission["permission_status"]' in IMPORTER
    assert "attribution_url" in IMPORTER and "permission_received_at" in IMPORTER


def test_source_register_is_authorised_for_adzuna_only():
    assert 'True if provider == "adzuna" else False' in CONNECTOR
    assert "apply_adzuna_permission(source)" in CONNECTOR


def test_labour_router_scope_reports_permission():
    assert '"permission_status": permission["permission_status"]' in ROUTER
    assert '"permission_received_at": permission["permission_received_at"]' in ROUTER
    assert '"permission_scope": permission["permission_scope"]' in ROUTER
    assert '"empirical_use_permitted": True,' in ROUTER
    assert '"attribution_required": permission["attribution_required"]' in ROUTER
    assert '"attribution_url": permission["attribution_url"]' in ROUTER
    assert '"attribution_note": ADZUNA_ATTRIBUTION_NOTE,' in ROUTER
    assert '"evidence_path": permission["evidence_path"]' in ROUTER
    assert "acquisition_mode" in ROUTER and 'live_trial_uat' in ROUTER


def test_labour_router_readiness_report_exposes_permission():
    assert '"permission": (source.config or {}).get("permission")' in ROUTER
    assert '"attribution_note": (source.config or {}).get("attribution_note")' in ROUTER


def test_signal_metadata_carries_permission_and_attribution():
    signals_block_end = "def generate_job_skill_demand_evidence("
    signals = PIPELINE[: PIPELINE.index(signals_block_end)]
    for marker in (
        "permission_status",
        "permission_received_at",
        "attribution_required",
        "attribution_url",
        "attribution_note",
        "evidence_path",
    ):
        assert marker in signals
    assert '"research_use": "academic_research_with_attribution"' in signals
    assert '"permission_status": permission.get("permission_status")' in signals
    assert '"attribution_url": permission.get("attribution_url")' in signals
    assert '"attribution_note": ADZUNA_ATTRIBUTION_NOTE if permission else None' in signals


def test_demand_evidence_copies_permission_metadata():
    evidence_block_start = PIPELINE.index("def generate_job_skill_demand_evidence(")
    evidence = PIPELINE[evidence_block_start:]
    for marker in ("attribution_url", "attribution_note", "permission_status", "evidence_path"):
        assert marker in evidence


def test_dossier_report_includes_attribution_note():
    assert "ADZUNA_ATTRIBUTION_NOTE" in ANALYTICS
    assert 'report["attribution"]' in ANALYTICS and "demand_evidence" in ANALYTICS
    assert "demand_evidence_uses_adzuna" in ANALYTICS


def test_pipeline_response_schema_keeps_scope_field():
    assert "trial_scope" in SCHEMA


def test_idempotency_guards_unchanged():
    assert "ADZUNA_JOB_PREFIX" in IMPORTER and '"ADZUNA-TRIAL-"' in IMPORTER
    assert "duplicate" in IMPORTER and "never replaced" in IMPORTER
    assert "PAGE_SIZE_MAX = 50" in IMPORTER
    assert "PAGE_NUMBER_MAX = 250" in IMPORTER
    assert "DEFAULT_REQUESTS_PER_MINUTE = 30" in IMPORTER


@BACKEND_ONLY
def test_frontend_attribution_and_permission_wording():
    assert "written academic research permission" in HELP_MANUAL
    assert "https://www.adzuna.co.za" in HELP_MANUAL
    assert "written academic research permission" in DATA_OPS
    assert "https://www.adzuna.co.za" in DATA_OPS
    assert "written_academic_permission" in DASHBOARD
    assert "https://www.adzuna.co.za" in DASHBOARD
    assert "written academic research permission" in VIEWS
    assert "https://www.adzuna.co.za" in VIEWS
    assert "written academic research permission" in ACTIONS


@EVIDENCE_ONLY
def test_evidence_register_contains_facts_and_no_credentials():
    for marker in ("Jesse Mutenyo", "2026-09-10", "permission_received_at", "attribution_url"):
        assert marker in EVIDENCE
    assert "ADZUNA_APP_KEY" not in EVIDENCE
    assert "api_key" not in EVIDENCE


@BACKEND_ONLY
def test_ui_does_not_warn_trial_data_is_ineligible():
    """The permission update must not reintroduce trial-ineligible warnings."""
    banned = ("not eligible for empirical research", "trial UAT only", "coverage/quality/usability")
    box_text = DATA_OPS.split("<h4>Adzuna Live API</h4>")[1].split("<h4>Labour-market Skill Pipeline</h4>")[0]
    for phrase in banned:
        assert phrase not in box_text, phrase