# backend/app/core/database.py

"""
Database engine and session management.
Production-ready PostgreSQL configuration.
"""

import logging
import re
from typing import Generator

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import (
    Session,
    scoped_session,
    sessionmaker,
)
from sqlalchemy.pool import QueuePool

from app.core.config import settings

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Schema Validation
# =========================================================

_SCHEMA_REGEX = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*$"
)


def validate_schema_name(
    schema: str,
) -> str:
    """
    Validate schema name to prevent SQL injection.
    """

    if not _SCHEMA_REGEX.match(schema):
        raise ValueError(
            f"Invalid schema name: {schema}"
        )

    return schema


DATABASE_SCHEMA = validate_schema_name(
    settings.DATABASE_SCHEMA
)

# =========================================================
# Engine Factory
# =========================================================


def create_database_engine() -> Engine:
    """
    Create configured SQLAlchemy engine.
    """

    connect_args = {}

    database_url = str(
        settings.DATABASE_URL
    )

    # -----------------------------------------------------
    # PostgreSQL Configuration
    # -----------------------------------------------------

    if database_url.startswith(
        "postgresql"
    ):

        ssl_mode = getattr(
            settings,
            "DATABASE_SSL_MODE",
            None,
        )

        if ssl_mode:
            connect_args["sslmode"] = (
                ssl_mode
            )

        connect_args.update(
            {
                "application_name": (
                    f"future-platform-"
                    f"{settings.ENVIRONMENT}"
                ),
                "options": (
                    f"-c search_path="
                    f"{DATABASE_SCHEMA},public"
                ),
            }
        )

    # -----------------------------------------------------
    # Create Engine
    # -----------------------------------------------------

    engine = create_engine(
        database_url,
        future=True,
        echo=settings.DATABASE_ECHO,
        poolclass=QueuePool,
        pool_size=max(
            1,
            settings.DATABASE_POOL_SIZE,
        ),
        max_overflow=max(
            0,
            settings.DATABASE_MAX_OVERFLOW,
        ),
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=30,
        connect_args=(
            connect_args
            if connect_args
            else {}
        ),
    )

    return engine


# =========================================================
# Engine Initialization
# =========================================================

engine = create_database_engine()

# =========================================================
# Connection Events
# =========================================================


@event.listens_for(engine, "connect")
def receive_connect(
    dbapi_connection,
    connection_record,
):
    """
    Connection established event.
    """

    logger.debug(
        "Database connection established"
    )


@event.listens_for(engine, "checkout")
def receive_checkout(
    dbapi_connection,
    connection_record,
    connection_proxy,
):
    """
    Connection checkout event.
    """

    logger.debug(
        "Database connection checked out"
    )


@event.listens_for(engine, "invalidate")
def receive_invalidate(
    dbapi_connection,
    connection_record,
    exception,
):
    """
    Connection invalidation event.
    """

    logger.warning(
        "Database connection invalidated"
    )


# =========================================================
# Session Factory
# =========================================================

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

# Scoped session support
ScopedSession = scoped_session(
    SessionLocal
)

# =========================================================
# FastAPI Database Dependency
# =========================================================


def get_db() -> Generator[
    Session,
    None,
    None,
]:
    """
    FastAPI database dependency.
    """

    db = SessionLocal()

    try:
        yield db

    except HTTPException:

        db.rollback()

        raise

    except Exception:

        db.rollback()

        logger.exception(
            "Database transaction rolled back"
        )

        raise

    finally:
        db.close()


# =========================================================
# Schema Initialization
# =========================================================


def init_schema(
    db_session: Session,
) -> None:
    """
    Ensure configured schema exists.
    """

    try:

        db_session.execute(
            text(
                f"CREATE SCHEMA "
                f"IF NOT EXISTS "
                f"{DATABASE_SCHEMA}"
            )
        )

        db_session.execute(
            text(
                f"SET search_path TO "
                f"{DATABASE_SCHEMA},public"
            )
        )

        db_session.commit()

        logger.info(
            "Database schema initialized"
        )

    except Exception:

        db_session.rollback()

        logger.exception(
            "Schema initialization failed"
        )

        raise


# =========================================================
# Database Health Check
# =========================================================


def check_database_connection() -> bool:
    """
    Validate database connectivity.
    """

    try:

        with engine.connect() as conn:
            conn.execute(
                text("SELECT 1")
            )

        return True

    except SQLAlchemyError:

        logger.exception(
            "Database health check failed"
        )

        return False
