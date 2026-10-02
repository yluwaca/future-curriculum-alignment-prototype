"""Verify the Windows-native PostgreSQL and pgvector boundary."""

import os

from sqlalchemy import create_engine, text


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            server_version = connection.execute(text("show server_version")).scalar_one()
            connection.execute(text("create extension if not exists vector"))
            vector_version = connection.execute(
                text("select extversion from pg_extension where extname = 'vector'")
            ).scalar_one_or_none()
            if not vector_version:
                raise SystemExit("pgvector extension is unavailable")
            dimensions = connection.execute(
                text("select vector_dims('[1,2,3]'::vector)")
            ).scalar_one()
            if dimensions != 3:
                raise SystemExit("pgvector functional check returned an unexpected result")
            print(
                f"PostgreSQL {server_version}; pgvector {vector_version}; "
                "vector operation verified; database ready"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
