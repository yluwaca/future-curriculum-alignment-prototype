from pathlib import Path

from app.services.portal_uat_service import PortalUATService


ROOT = Path(__file__).parents[2]


def test_uat_check_distinguishes_pass_block_and_failure():
    service = PortalUATService()
    assert service._check("a", "A", True, "ok")["status"] == "passed"
    assert service._check("b", "B", True, "blocked", expected_block=True)["status"] == "expected_block"
    assert service._check("c", "C", False, "bad")["status"] == "failed"


def test_portal_uat_is_admin_only_and_archives_hashed_report():
    router = (ROOT / "backend/app/routers/operations.py").read_text(encoding="utf-8")
    service = (ROOT / "backend/app/services/portal_uat_service.py").read_text(encoding="utf-8")
    assert '@router.post("/portal-uat/run")' in router
    assert 'require_role("ADMIN")' in router
    assert 'report_type="portal_acceptance_uat"' in service
    assert "payload_hash=report_hash" in service
    assert 'event_type="portal_uat"' in service


def test_portal_runner_is_non_destructive_and_covers_both_paths():
    service = (ROOT / "backend/app/services/portal_uat_service.py").read_text(encoding="utf-8")
    assert '"golden_path": golden' in service
    assert '"failure_path": failure' in service
    assert "validated_regeneration_service.readiness(db)" in service
    assert "recommendation_governance_service.readiness(db)" in service
    assert ".run(db" not in service
    assert ".generate_pack(" not in service
    assert ".decide(" not in service


def test_system_operations_exposes_portal_uat_runner_and_results():
    page = (ROOT / "frontend/system-operations.html").read_text(encoding="utf-8")
    actions = (ROOT / "frontend/dashboard-actions.js").read_text(encoding="utf-8")
    views = (ROOT / "frontend/dashboard-views.js").read_text(encoding="utf-8")
    assert 'id="runPortalUatBtn"' in page
    assert 'id="portalUatPanel"' in page
    assert "PORTAL_UAT_RUN" in actions
    assert "function renderPortalUat()" in views
    assert "Safe Blocks" in views
    assert "showSpinner, hideSpinner" in actions


def test_standalone_pages_do_not_require_dashboard_status_box():
    state = (ROOT / "frontend/dashboard-state.js").read_text(encoding="utf-8")
    assert state.count("if (!box) return;") >= 2
