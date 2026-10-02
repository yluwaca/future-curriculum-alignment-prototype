"""Dashboard and documentation smoke checks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_DIR / "frontend"


DASHBOARD_REQUIRED_MARKERS = [
    "Gap Evidence Drill-down",
    "Decision Portal",
    "shared-nav.js",
    "initPage",
    "executive",
]

ARCHITECTURE_REQUIRED_MARKERS = [
    "Skill gap drill-down",
    "ingestion",
    "Dashboard overview",
]

DOC_REQUIRED_FILES = [
    PROJECT_DIR / "docs" / "architecture_overview.md",
    PROJECT_DIR / "docs" / "implementation_status_checklist.md",
    PROJECT_DIR / "docs" / "supervisor_progress_current.md",
    PROJECT_DIR / "docs" / "backend_api_inventory.csv",
]


def test_dashboard_contains_production_ui_markers() -> None:
    dashboard = (FRONTEND_DIR / "dashboard.html").read_text(encoding="utf-8-sig")
    missing = [marker for marker in DASHBOARD_REQUIRED_MARKERS if marker not in dashboard]
    assert not missing, f"Missing dashboard markers: {missing}"


def test_architecture_page_contains_current_state_markers() -> None:
    page = (FRONTEND_DIR / "ingestion_architecture.html").read_text(encoding="utf-8-sig")
    lower_page = page.lower()
    missing = [marker for marker in ARCHITECTURE_REQUIRED_MARKERS if marker.lower() not in lower_page]
    assert not missing, f"Missing architecture page markers: {missing}"


def test_supervisor_documentation_files_exist_and_are_current() -> None:
    missing_files = [str(path) for path in DOC_REQUIRED_FILES if not path.exists()]
    assert not missing_files, f"Missing documentation files: {missing_files}"
    for path in DOC_REQUIRED_FILES[:3]:
        content = path.read_text(encoding="utf-8-sig")
        assert "2026-06-25" in content or "2026-06-26" in content, f"{path} does not show a current update date"


def test_dashboard_javascript_syntax(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available for dashboard JavaScript syntax checking")

    html = (FRONTEND_DIR / "dashboard.html").read_text(encoding="utf-8-sig")
    scripts = []
    pos = 0
    while True:
        start = html.find("<script", pos)
        if start == -1:
            break
        start = html.find(">", start) + 1
        end = html.find("</script>", start)
        if end == -1:
            break
        scripts.append(html[start:end])
        pos = end + len("</script>")

    script_file = tmp_path / "dashboard.js"
    script_file.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run([node, "--check", str(script_file)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
