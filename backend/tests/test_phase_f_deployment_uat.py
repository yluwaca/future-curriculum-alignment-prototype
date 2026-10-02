"""Production deployment and UAT readiness checks."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_DIR = Path(__file__).resolve().parents[2]


def test_deployment_readiness_has_expected_sections(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/operations/deployment-readiness", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phase"] == "Deployment & UAT Readiness"
    assert 0 <= payload["score"] <= 1
    assert {"deployment", "nginx_https", "uat", "documentation"}.issubset(payload.keys())
    assert payload["deployment"]["compose_services"]["backend"] is True
    assert payload["nginx_https"]["checks"]["https_listener"] is True


def test_deployment_and_uat_files_exist() -> None:
    required = [
        "backend/Dockerfile",
        "docker-compose.yml",
        ".env.production.example",
        "nginx/conf/future.production.conf",
        "tools/run_uat_checks.py",
        "docs/uat_script.md",
        "docs/production_phase_f_deployment_uat.md",
        "docs/final_production_readiness_a_to_f.md",
    ]
    missing = [item for item in required if not (PROJECT_DIR / item).exists()]
    assert not missing, f"Missing deployment/UAT files: {missing}"


def test_uat_script_is_importable_and_has_main() -> None:
    import importlib.util

    script = PROJECT_DIR / "tools" / "run_uat_checks.py"
    spec = importlib.util.spec_from_file_location("run_uat_checks", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
