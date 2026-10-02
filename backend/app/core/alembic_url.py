"""Helpers for safely transferring database URLs through Alembic ConfigParser."""


def escape_for_alembic(database_url: str) -> str:
    """Escape percent signs consumed by ConfigParser interpolation.

    URL-encoded credentials contain percent sequences such as ``%40``. Alembic stores
    its main options in a ConfigParser, where literal percent signs must be doubled.
    ConfigParser converts them back when Alembic reads the option, so the database sees
    the original URL and credentials.
    """

    if not database_url:
        raise ValueError("database_url must not be empty")
    return database_url.replace("%", "%%")
