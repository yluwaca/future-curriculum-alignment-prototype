"""Alembic migration verification for the configured database."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app.db.session import engine


BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.migration
@pytest.mark.db
def test_database_revision_matches_alembic_heads() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    expected_heads = set(script.get_heads())

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_heads = set(context.get_current_heads())

    assert current_heads, "Database has no recorded Alembic revision"
    assert current_heads == expected_heads, (
        f"Database migration heads {sorted(current_heads)} do not match script heads {sorted(expected_heads)}"
    )


@pytest.mark.migration
def test_alembic_has_single_head() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected one Alembic head, found {heads}"
