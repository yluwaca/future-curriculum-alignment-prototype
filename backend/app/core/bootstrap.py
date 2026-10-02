# backend/app/core/bootstrap.py

"""
FUTURE Platform Bootstrap Services.

Responsibilities:

- Database migration execution
- Development admin bootstrap
- Startup validation
- RBAC initialization
- Predictive platform initialization
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import logging
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password

from app.models.user import User
from app.models.role import Role
from app.models.user_role import UserRole

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Startup Validation
# =========================================================


PRODUCTION_SECRET_PROVIDERS = {
    "environment_injected",
    "docker_secret",
    "kubernetes_secret",
    "vault",
    "cloud_secret_manager",
}

UNSAFE_SECRET_MARKERS = {
    "change-me",
    "changeme",
    "change-this",
    "password",
    "secret",
    "future_change_me",
}


def production_configuration_issues(settings_obj=settings) -> list[str]:
    """Return fail-closed production configuration findings without secret values."""
    if not settings_obj.is_production:
        return []
    issues: list[str] = []
    secret = str(settings_obj.SECRET_KEY or "")
    lowered_secret = secret.lower()
    if len(secret) < 48 or len(set(secret)) < 16:
        issues.append("SECRET_KEY must be at least 48 characters with adequate character diversity.")
    if any(marker in lowered_secret for marker in UNSAFE_SECRET_MARKERS):
        issues.append("SECRET_KEY contains a prohibited placeholder or common secret marker.")
    if settings_obj.SECRET_PROVIDER not in PRODUCTION_SECRET_PROVIDERS:
        issues.append("SECRET_PROVIDER must identify an approved managed injection mechanism.")
    if not settings_obj.SECRET_ROTATION_OWNER:
        issues.append("SECRET_ROTATION_OWNER must identify the accountable secret custodian.")
    if not 1 <= int(settings_obj.SECRET_ROTATION_DAYS) <= 365:
        issues.append("SECRET_ROTATION_DAYS must be between 1 and 365.")

    database_url = str(settings_obj.DATABASE_URL or "")
    parsed = urlparse(database_url.replace("postgresql+psycopg2://", "postgresql://", 1))
    database_password = parsed.password or ""
    if not database_password or any(marker in database_password.lower() for marker in UNSAFE_SECRET_MARKERS):
        issues.append("DATABASE_URL must contain a non-placeholder managed database credential.")
    if settings_obj.DATABASE_SSL_MODE not in {"require", "verify-ca", "verify-full"}:
        issues.append("DATABASE_SSL_MODE must require encrypted database transport.")
    if settings_obj.DEBUG or settings_obj.RELOAD:
        issues.append("DEBUG and RELOAD must be disabled in production.")
    if settings_obj.ENABLE_DOCS:
        issues.append("ENABLE_DOCS must be disabled in production.")
    if settings_obj.ENABLE_BOOTSTRAP_ADMIN:
        issues.append("ENABLE_BOOTSTRAP_ADMIN must be disabled in production.")
    if not settings_obj.REQUIRE_HTTPS or not settings_obj.TRUST_PROXY_HEADERS:
        issues.append("REQUIRE_HTTPS and TRUST_PROXY_HEADERS must be enabled behind the TLS proxy.")
    origins = [str(value).lower() for value in settings_obj.CORS_ORIGINS]
    if not origins or any(
        value == "*" or not value.startswith("https://")
        or "localhost" in value or "127.0.0.1" in value
        for value in origins
    ):
        issues.append("CORS_ORIGINS must contain only explicit production HTTPS origins.")
    if settings_obj.OIDC_ENABLED and not settings_obj.OIDC_CLIENT_SECRET:
        issues.append("OIDC_CLIENT_SECRET is required when OIDC is enabled.")
    return issues


def validate_environment() -> None:
    """
    Validate critical runtime configuration.
    """

    logger.info(
        "[BOOTSTRAP] Environment=%s",
        settings.ENVIRONMENT,
    )

    if not settings.SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY not configured"
        )

    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL not configured"
        )
    production_issues = production_configuration_issues(settings)
    if production_issues:
        raise RuntimeError(
            "Unsafe production configuration: " + " | ".join(production_issues)
        )

# =========================================================
# Bootstrap Admin User
# =========================================================


def ensure_admin_user(
    db: Session,
) -> None:
    """
    Create or repair the configured bootstrap admin account.

    Bootstrap admin must always be active, approved, marked as admin,
    and assigned the admin RBAC role so the first login can approve
    other users.
    """

    if settings.is_production:

        logger.info(
            "[BOOTSTRAP] Production mode - "
            "admin bootstrap skipped"
        )

        return

    enable_bootstrap = getattr(
        settings,
        "ENABLE_BOOTSTRAP_ADMIN",
        True,
    )

    if not enable_bootstrap:

        logger.info(
            "[BOOTSTRAP] Admin bootstrap disabled"
        )

        return

    admin_identity_id = getattr(
        settings,
        "BOOTSTRAP_ADMIN_USERNAME",
        "admin",
    )

    admin_email = getattr(
        settings,
        "BOOTSTRAP_ADMIN_EMAIL",
        "admin@future-platform.local",
    ).lower()

    admin_password = getattr(
        settings,
        "BOOTSTRAP_ADMIN_PASSWORD",
        None,
    )

    if not admin_password:

        logger.warning(
            "[BOOTSTRAP] "
            "BOOTSTRAP_ADMIN_PASSWORD "
            "not configured"
        )

        return

    try:

        admin = (
            db.query(User)
            .filter(
                (User.identity_id == admin_identity_id)
                | (User.email == admin_email)
            )
            .first()
        )

        now = datetime.now(timezone.utc)

        if admin is None:
            admin = User(
                identity_id=admin_identity_id,
                email=admin_email,
                password_hash=hash_password(
                    admin_password
                ),
                identity_type="human",
                status="active",
                is_active=True,
                is_admin=True,
                approval_status="approved",
                approved_by=admin_identity_id,
                approved_at=now,
            )
            db.add(admin)
            logger.info(
                "[BOOTSTRAP] Admin account created"
            )
        else:
            admin.email = admin_email
            admin.status = "active"
            admin.is_active = True
            admin.is_admin = True
            admin.approval_status = "approved"
            admin.approved_by = admin.approved_by or admin_identity_id
            admin.approved_at = admin.approved_at or now
            logger.info(
                "[BOOTSTRAP] Admin account verified"
            )

        admin_role = (
            db.query(Role)
            .filter(Role.role_id == "admin")
            .first()
        )

        if admin_role:
            existing_role = (
                db.query(UserRole)
                .filter(
                    UserRole.identity_id == admin.identity_id,
                    UserRole.role_id == admin_role.role_id,
                )
                .first()
            )

            if existing_role:
                existing_role.is_active = True
            else:
                db.add(
                    UserRole(
                        identity_id=admin.identity_id,
                        role_id=admin_role.role_id,
                        is_active=True,
                    )
                )
        else:
            logger.warning(
                "[BOOTSTRAP] Admin role missing; "
                "is_admin flag was still applied"
            )

        db.commit()

    except SQLAlchemyError:

        db.rollback()

        logger.exception(
            "[BOOTSTRAP] "
            "Failed to create or repair admin"
        )

        raise
# =========================================================
# Migration Runner
# =========================================================


def run_migrations() -> None:
    """
    Execute Alembic migrations.
    """

    try:

        project_root = (
            Path(__file__)
            .resolve()
            .parent.parent.parent
        )

        alembic_ini = (
            project_root
            / "alembic.ini"
        )

        migrations_path = (
            project_root
            / "migrations"
        )

        if not alembic_ini.exists():

            raise FileNotFoundError(
                f"Missing Alembic config: "
                f"{alembic_ini}"
            )

        if not migrations_path.exists():

            raise FileNotFoundError(
                f"Missing migrations path: "
                f"{migrations_path}"
            )

        alembic_cfg = Config(
            str(alembic_ini)
        )

        alembic_cfg.set_main_option(
            "script_location",
            str(migrations_path),
        )

        alembic_cfg.set_main_option(
            "sqlalchemy.url",
            str(settings.DATABASE_URL),
        )

        logger.info(
            "[BOOTSTRAP] "
            "Running Alembic migrations"
        )

        command.upgrade(
            alembic_cfg,
            "head",
        )

        logger.info(
            "[BOOTSTRAP] "
            "Migrations completed"
        )

    except Exception:

        logger.exception(
            "[BOOTSTRAP] "
            "Migration execution failed"
        )

        raise

# =========================================================
# RBAC Bootstrap Hook
# =========================================================


def initialize_rbac() -> None:
    """
    Future RBAC startup hook.
    """

    logger.info(
        "[BOOTSTRAP] RBAC initialized"
    )

# =========================================================
# Predictive Platform Bootstrap Hook
# =========================================================


def initialize_predictive_platform() -> None:
    """
    Future predictive engine startup hook.
    """

    logger.info(
        "[BOOTSTRAP] "
        "Predictive platform initialized"
    )

# =========================================================
# Startup Summary
# =========================================================


def startup_summary() -> None:
    """
    Emit startup summary.
    """

    logger.info(
        "======================================"
    )

    logger.info(
        "FUTURE Platform Bootstrap Complete"
    )

    logger.info(
        "Environment : %s",
        settings.ENVIRONMENT,
    )

    logger.info(
        "Database    : Connected"
    )

    logger.info(
        "RBAC        : Ready"
    )

    logger.info(
        "Predictive  : Ready"
    )

    logger.info(
        "======================================"
    )
