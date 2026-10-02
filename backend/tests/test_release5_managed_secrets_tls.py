from pathlib import Path
from types import SimpleNamespace

from app.core.bootstrap import production_configuration_issues
from app.services.deployment_uat_service import DeploymentUATService


ROOT = Path(__file__).parents[2]


def production_settings(**overrides):
    values = {
        "is_production": True,
        "SECRET_KEY": "9xK!7pQ@2vM#8rT$4zN%6cB&1sD*5fG_3hJ-0wL+AaEeIiOo",
        "SECRET_PROVIDER": "cloud_secret_manager",
        "SECRET_ROTATION_OWNER": "institutional-security",
        "SECRET_ROTATION_DAYS": 90,
        "DATABASE_URL": "postgresql://future:Db9!ManagedCredential@postgres/future",
        "DATABASE_SSL_MODE": "verify-full",
        "DEBUG": False,
        "RELOAD": False,
        "ENABLE_DOCS": False,
        "ENABLE_BOOTSTRAP_ADMIN": False,
        "REQUIRE_HTTPS": True,
        "TRUST_PROXY_HEADERS": True,
        "CORS_ORIGINS": ["https://future.example.edu"],
        "OIDC_ENABLED": False,
        "OIDC_CLIENT_SECRET": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_secure_production_configuration_has_no_findings():
    assert production_configuration_issues(production_settings()) == []


def test_production_rejects_placeholders_and_development_features():
    issues = production_configuration_issues(production_settings(
        SECRET_KEY="change-me",
        SECRET_PROVIDER="development_env",
        SECRET_ROTATION_OWNER=None,
        DATABASE_URL="postgresql://future:password@postgres/future",
        DATABASE_SSL_MODE="prefer",
        DEBUG=True,
        RELOAD=True,
        ENABLE_DOCS=True,
        ENABLE_BOOTSTRAP_ADMIN=True,
        REQUIRE_HTTPS=False,
        TRUST_PROXY_HEADERS=False,
        CORS_ORIGINS=["http://localhost:8080", "*"],
    ))
    joined = " ".join(issues)
    for expected in (
        "SECRET_KEY", "SECRET_PROVIDER", "SECRET_ROTATION_OWNER",
        "DATABASE_URL", "DATABASE_SSL_MODE", "DEBUG and RELOAD",
        "ENABLE_DOCS", "ENABLE_BOOTSTRAP_ADMIN", "REQUIRE_HTTPS",
        "CORS_ORIGINS",
    ):
        assert expected in joined


def test_compose_has_no_production_secret_fallbacks():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SECRET_KEY:-" not in compose
    assert "POSTGRES_PASSWORD:-" not in compose
    assert "SECRET_KEY:?" in compose
    assert "POSTGRES_PASSWORD:?" in compose
    assert "ssl=on" in compose


def test_nginx_tls_and_security_headers_are_hardened():
    nginx = (ROOT / "nginx/conf/future.production.conf").read_text(encoding="utf-8")
    for marker in (
        "ssl_protocols TLSv1.2 TLSv1.3",
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "Permissions-Policy",
        "ssl_session_tickets off",
        "X-Forwarded-Port 443",
        "server_tokens off",
    ):
        assert marker in nginx


def test_deployment_readiness_reports_secrets_and_tls_controls():
    summary = DeploymentUATService().deployment_readiness_summary()
    assert summary["managed_secrets"]["quality_score"] == 1.0
    assert summary["nginx_https"]["quality_score"] == 1.0
    assert not summary["managed_secrets"]["issues"]


def test_standalone_operations_can_render_readiness_without_optional_shell_elements():
    actions = (ROOT / "frontend/dashboard-actions.js").read_text(encoding="utf-8")
    utilities = (ROOT / "frontend/dashboard-utils.js").read_text(encoding="utf-8")
    assert "renderSecurityReadiness, renderDeploymentReadiness" in actions
    assert "if (!container) return;" in utilities
