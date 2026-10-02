"""
Tests for frontend JavaScript file syntax validation.
Uses Node.js --check to verify all JS files parse without errors.
"""

import pytest
import subprocess
import os
from pathlib import Path

DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", str(DEFAULT_FRONTEND_DIR)))

JS_FILES = [
    "admin.js",
    "auth.js",
    "config.js",
    "login.js",
    "register.js",
    "dashboard-main.js",
    "dashboard-actions.js",
    "shared-nav.js",
    "dashboard-state.js",
    "dashboard-utils.js",
    "dashboard-views.js",
    "recommendations.js",
    "ingestion-architecture.js",
]


@pytest.mark.smoke
class TestJavaScriptSyntax:
    """Validate all frontend JS files parse without syntax errors."""

    @pytest.mark.parametrize("js_file", JS_FILES)
    def test_js_syntax(self, js_file):
        filepath = FRONTEND_DIR / js_file
        if not filepath.exists():
            pytest.skip(f"{js_file} not found")
        result = subprocess.run(
            ["node", "--check", str(filepath)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"Syntax error in {js_file}:\n{result.stderr}"
        )


@pytest.mark.smoke
class TestHTMLFiles:
    """Validate HTML files are well-formed."""

    HTML_FILES = [
        "dashboard.html",
        "model-lab.html",
        "data-operations.html",
        "system-operations.html",
        "admin.html",
        "index.html",
        "register.html",
        "recommendations.html",
        "ingestion_architecture.html",
    ]

    @pytest.mark.parametrize("html_file", HTML_FILES)
    def test_html_has_doctype(self, html_file):
        filepath = FRONTEND_DIR / html_file
        if not filepath.exists():
            pytest.skip(f"{html_file} not found")
        content = filepath.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content, f"{html_file} missing DOCTYPE"

    @pytest.mark.parametrize("html_file", HTML_FILES)
    def test_html_has_closing_tags(self, html_file):
        filepath = FRONTEND_DIR / html_file
        if not filepath.exists():
            pytest.skip(f"{html_file} not found")
        content = filepath.read_text(encoding="utf-8")
        assert content.count("<html") == content.count("</html>"), (
            f"{html_file} has mismatched <html> tags"
        )
        assert content.count("<body") == content.count("</body>"), (
            f"{html_file} has mismatched <body> tags"
        )

    @pytest.mark.parametrize("html_file", HTML_FILES)
    def test_html_no_stale_script_tags(self, html_file):
        """Check for stale </script> tags that break ES modules."""
        filepath = FRONTEND_DIR / html_file
        if not filepath.exists():
            pytest.skip(f"{html_file} not found")
        content = filepath.read_text(encoding="utf-8")
        opens = content.count("<script")
        closes = content.count("</script>")
        assert opens == closes, (
            f"{html_file} has {opens} <script> but {closes} </script>"
        )

    @pytest.mark.parametrize("html_file", HTML_FILES)
    def test_html_css_links_valid(self, html_file):
        filepath = FRONTEND_DIR / html_file
        if not filepath.exists():
            pytest.skip(f"{html_file} not found")
        content = filepath.read_text(encoding="utf-8")
        import re
        css_links = re.findall(r'href="([^"]+\.css)"', content)
        for css_href in css_links:
            css_path = FRONTEND_DIR / css_href
            assert css_path.exists(), (
                f"{html_file} links to {css_href} but file not found"
            )


    def test_decision_dashboard_has_no_admin_operation_controls(self):
        content = (FRONTEND_DIR / "dashboard.html").read_text(encoding="utf-8")
        forbidden_controls = [
            "trainXgboostBtn",
            "trainLstmBtn",
            "runGenericIntakeBtn",
            "runCheImportBtn",
            "runStatsImportBtn",
            "generateBackupManifestBtn",
        ]
        for control in forbidden_controls:
            assert control not in content, f"dashboard.html should not expose {control}"

    def test_new_role_focused_pages_use_shared_nav(self):
        for html_file in ["dashboard.html", "model-lab.html", "data-operations.html", "system-operations.html"]:
            content = (FRONTEND_DIR / html_file).read_text(encoding="utf-8")
            assert "shared-nav.js" in content, f"{html_file} should use shared navigation"
            assert "initPage" in content, f"{html_file} should initialise shared page shell"

    def test_model_lab_exposes_phase7_lifecycle_controls(self):
        content = (FRONTEND_DIR / "model-lab.html").read_text(encoding="utf-8")
        for control in [
            "refreshModelRegistryBtn",
            "checkModelGatesBtn",
            "recordModelTestsBtn",
            "evaluateModelBtn",
            "approveModelBtn",
            "promoteModelBtn",
            "rejectModelBtn",
            "rollbackModelBtn",
        ]:
            assert control in content, f"model-lab.html missing {control}"
