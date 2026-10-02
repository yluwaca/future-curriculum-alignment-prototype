"""Prevent duplicate ES-module state caused by mismatched cache query strings."""

import re
from pathlib import Path


def test_dashboard_state_is_imported_with_one_canonical_url():
    frontend = Path(__file__).parents[2] / "frontend"
    imports = []
    for path in frontend.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        imports.extend(re.findall(r"dashboard-state\.js(?:\?v=([A-Za-z0-9_-]+))?", text))
    versions = {version for version in imports if version}
    assert versions == {"20260912d"}


def test_specialist_pages_load_the_same_dashboard_entry_module():
    frontend = Path(__file__).parents[2] / "frontend"
    versions = set()
    for name in ("dashboard.html", "data-operations.html", "model-lab.html", "system-operations.html"):
        text = (frontend / name).read_text(encoding="utf-8")
        match = re.search(r"dashboard-main\.js\?v=([A-Za-z0-9_-]+)", text)
        assert match, name
        versions.add(match.group(1))
    assert versions == {"20260912d"}
