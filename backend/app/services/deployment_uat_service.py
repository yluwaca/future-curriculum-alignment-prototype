"""
Production service: deployment and UAT readiness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


class DeploymentUATService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    REQUIRED_DEPLOYMENT_FILES = [
        "backend/Dockerfile",
        "docker-compose.yml",
        ".env.production.example",
        "nginx/conf/future.production.conf",
    ]
    REQUIRED_UAT_FILES = [
        "tools/run_uat_checks.py",
        "docs/uat_script.md",
        "docs/production_phase_f_deployment_uat.md",
        "docs/final_production_readiness_a_to_f.md",
    ]

    def deployment_readiness_summary(self) -> Dict[str, Any]:
        deployment = self.deployment_files_summary()
        secrets = self.managed_secrets_summary()
        nginx = self.nginx_https_summary()
        uat = self.uat_summary()
        docs = self.documentation_summary()
        score = round(
            (
                deployment["quality_score"] * 0.20
                + secrets["quality_score"] * 0.25
                + nginx["quality_score"] * 0.25
                + uat["quality_score"] * 0.15
                + docs["quality_score"] * 0.15
            ),
            4,
        )
        issues = deployment["issues"] + secrets["issues"] + nginx["issues"] + uat["issues"] + docs["issues"]
        return {
            "phase": "Deployment & UAT Readiness",
            "score": score,
            "status": "ready" if score >= 0.75 and not issues else "needs_attention",
            "deployment": deployment,
            "managed_secrets": secrets,
            "nginx_https": nginx,
            "uat": uat,
            "documentation": docs,
            "issues": issues[:12],
            "next_actions": [
                "Set production secrets in a real environment file or platform secret store.",
                "Install valid TLS certificates at nginx/certs/fullchain.pem and nginx/certs/privkey.pem.",
                "Run docker compose build and docker compose up in a deployment environment.",
                "Run UAT with a test user and archive the UAT output for supervisor/governance review.",
            ],
        }

    def managed_secrets_summary(self) -> Dict[str, Any]:
        compose = self.read_text("docker-compose.yml")
        template = self.read_text(".env.production.example")
        bootstrap = self.read_text("backend/app/core/bootstrap.py")
        checks = {
            "no_compose_secret_fallbacks": "SECRET_KEY:-" not in compose and "POSTGRES_PASSWORD:-" not in compose,
            "required_secret_injection": "SECRET_KEY:?" in compose and "POSTGRES_PASSWORD:?" in compose,
            "provider_and_rotation_metadata": all(
                key in template for key in ("SECRET_PROVIDER", "SECRET_ROTATION_OWNER", "SECRET_ROTATION_DAYS")
            ),
            "production_fail_closed_validation": "production_configuration_issues" in bootstrap,
            "database_tls_required": "DATABASE_SSL_MODE=require" in template and "ssl=on" in compose,
            "explicit_https_cors": "CORS_ORIGINS=https://" in template and "CORS_ALLOW_ORIGINS" not in compose,
            "unsafe_runtime_features_disabled": all(
                marker in template
                for marker in ("DEBUG=false", "RELOAD=false", "ENABLE_DOCS=false", "ENABLE_BOOTSTRAP_ADMIN=false")
            ),
        }
        issues = [f"Managed-secret check failed: {key}" for key, ok in checks.items() if not ok]
        return {
            "quality_score": round(sum(checks.values()) / len(checks), 4),
            "checks": checks,
            "issues": issues,
            "note": "Readiness verifies fail-closed configuration only; deployment owners must inject real values and record rotation evidence.",
        }

    def deployment_files_summary(self) -> Dict[str, Any]:
        files = self.file_status(self.REQUIRED_DEPLOYMENT_FILES)
        missing = [item["path"] for item in files if not item["exists"]]
        compose_text = self.read_text("docker-compose.yml")
        dockerfile_text = self.read_text("backend/Dockerfile")
        issues: List[str] = []
        if missing:
            issues.append(f"Missing deployment files: {', '.join(missing)}")
        if "postgres" not in compose_text or "backend" not in compose_text or "nginx" not in compose_text:
            issues.append("docker-compose.yml does not define postgres, backend, and nginx services.")
        if "uvicorn" not in dockerfile_text:
            issues.append("Backend Dockerfile does not start uvicorn.")
        quality = self.quality_from_missing(files, issues)
        return {
            "quality_score": quality,
            "files": files,
            "compose_services": {
                "postgres": "postgres" in compose_text,
                "backend": "backend" in compose_text,
                "nginx": "nginx" in compose_text,
            },
            "issues": issues,
        }

    def nginx_https_summary(self) -> Dict[str, Any]:
        text = self.read_text("nginx/conf/future.production.conf")
        certificate_path = self.PROJECT_ROOT / "nginx/certs/fullchain.pem"
        private_key_path = self.PROJECT_ROOT / "nginx/certs/privkey.pem"
        checks = {
            "https_listener": "listen 443 ssl" in text,
            "http_redirect": "return 301 https://" in text,
            "api_proxy": "proxy_pass http://backend:8000" in text,
            "tls_certificate_paths": "ssl_certificate" in text and "ssl_certificate_key" in text,
            "certificate_installed": certificate_path.is_file() and certificate_path.stat().st_size > 0,
            "private_key_installed": private_key_path.is_file() and private_key_path.stat().st_size > 0,
            "security_headers": "X-Content-Type-Options" in text and "X-Frame-Options" in text,
            "hsts": "Strict-Transport-Security" in text,
            "content_security_policy": "Content-Security-Policy" in text,
            "tls_sessions_hardened": "ssl_session_tickets off" in text,
            "proxy_forwarding": "X-Forwarded-Proto" in text and "X-Forwarded-Port" in text,
        }
        score_keys = [
            key for key in checks
            if key not in {"certificate_installed", "private_key_installed"}
        ]
        issues = [
            key for key, ok in checks.items()
            if not ok and key in score_keys
        ]
        return {
            "quality_score": round(sum(1 for key in score_keys if checks[key]) / max(len(score_keys), 1), 4),
            "checks": checks,
            "certificate_note": (
                "Certificate presence is checked in nginx/certs. A deployment owner must still verify "
                "the certificate chain, hostname, expiry, and live HTTPS endpoint in the target environment."
            ),
            "issues": [f"NGINX HTTPS check failed: {item}" for item in issues],
        }

    def uat_summary(self) -> Dict[str, Any]:
        files = self.file_status(self.REQUIRED_UAT_FILES[:2])
        missing = [item["path"] for item in files if not item["exists"]]
        script_text = self.read_text("tools/run_uat_checks.py")
        checks = {
            "login_check": "/api/v1/auth/login" in script_text,
            "dashboard_check": "dashboard.html" in script_text,
            "phase_readiness_checks": "security-readiness" in script_text and "deployment-readiness" in script_text,
            "report_output": "--output" in script_text,
        }
        issues = [f"Missing UAT file: {item}" for item in missing]
        issues += [f"UAT script check missing: {key}" for key, ok in checks.items() if not ok]
        return {
            "quality_score": round((sum(1 for ok in checks.values() if ok) + sum(1 for item in files if item["exists"])) / (len(checks) + len(files)), 4),
            "files": files,
            "checks": checks,
            "issues": issues,
        }

    def documentation_summary(self) -> Dict[str, Any]:
        files = self.file_status(self.REQUIRED_UAT_FILES[2:])
        missing = [item["path"] for item in files if not item["exists"]]
        final_doc = self.read_text("docs/final_production_readiness_a_to_f.md")
        phase_mentions = [f"Phase {letter}" for letter in "ABCDEF"]
        checks = {phase: phase in final_doc for phase in phase_mentions}
        issues = [f"Missing documentation file: {item}" for item in missing]
        issues += [f"Final readiness document does not mention {phase}" for phase, ok in checks.items() if not ok]
        return {
            "quality_score": round((sum(1 for ok in checks.values() if ok) + sum(1 for item in files if item["exists"])) / (len(checks) + len(files)), 4),
            "files": files,
            "checks": checks,
            "issues": issues,
        }

    def file_status(self, relative_paths: List[str]) -> List[Dict[str, Any]]:
        statuses = []
        for relative in relative_paths:
            path = self.PROJECT_ROOT / relative
            statuses.append(
                {
                    "path": relative,
                    "exists": path.exists(),
                    "size_bytes": path.stat().st_size if path.exists() else 0,
                }
            )
        return statuses

    def read_text(self, relative_path: str) -> str:
        path = self.PROJECT_ROOT / relative_path
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def quality_from_missing(files: List[Dict[str, Any]], issues: List[str]) -> float:
        file_score = sum(1 for item in files if item["exists"]) / max(len(files), 1)
        issue_penalty = min(len(issues) * 0.15, 0.60)
        return round(max(0.0, file_score - issue_penalty), 4)


deployment_uat_service = DeploymentUATService()

