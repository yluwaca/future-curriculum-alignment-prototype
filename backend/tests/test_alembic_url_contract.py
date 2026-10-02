from configparser import ConfigParser

import pytest

from app.core.alembic_url import escape_for_alembic


def test_encoded_password_survives_alembic_config_interpolation() -> None:
    url = "postgresql+psycopg2://future:%40%40FUTURE_Mscoa%24%242016@127.0.0.1:5432/future"
    parser = ConfigParser()
    parser.add_section("alembic")
    parser.set("alembic", "sqlalchemy.url", escape_for_alembic(url))

    assert parser.get("alembic", "sqlalchemy.url") == url


def test_empty_database_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        escape_for_alembic("")
