from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_dashboard_renders_shell_and_progress_before_slow_requests_finish():
    actions = (ROOT / "frontend/dashboard-actions.js").read_text(encoding="utf-8")
    assert "renderAll();" in actions
    assert "Loading live dashboard data (0/22)" in actions
    assert "loadedDashboardRequests" in actions
    assert "Core dashboard loaded. Loading evidence details" in actions
    assert "getJson(url, fallback, 60000)" in actions


def test_core_values_render_before_secondary_evidence_details():
    actions = (ROOT / "frontend/dashboard-actions.js").read_text(encoding="utf-8")
    core_render = actions.index("// Core dashboard values are now usable")
    details = actions.index("state.documentDetails = await Promise.all")
    assert core_render < details


def test_specialist_entry_view_switches_before_dashboard_load_completes():
    main = (ROOT / "frontend/dashboard-main.js").read_text(encoding="utf-8")
    immediate = main.index("switchView(window.FUTURE_DEFAULT_VIEW);")
    load = main.index("loadDashboard().then")
    assert immediate < load


def test_standalone_optional_status_and_toast_elements_are_safe():
    state = (ROOT / "frontend/dashboard-state.js").read_text(encoding="utf-8")
    utils = (ROOT / "frontend/dashboard-utils.js").read_text(encoding="utf-8")
    assert state.count("if (!box) return;") >= 2
    assert "if (!container) return;" in utils
