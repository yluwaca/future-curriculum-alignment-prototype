"""require pgvector backend for semantic vector repository

Revision ID: pgvector_required_01
Revises: job_imported_01
Create Date: 2026-07-26

This migration intentionally fails when PostgreSQL pgvector is not available.
JSONB embedding storage may remain for audit/compatibility, but production
semantic vector search requires a native vector column and index.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "pgvector_required_01"
down_revision = "job_imported_01"
branch_labels = None
depends_on = None


VECTOR_DIMENSIONS = 768


def upgrade() -> None:
    conn = op.get_bind()

    available = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector')")
    ).scalar()
    if not available:
        raise RuntimeError(
            "PostgreSQL pgvector extension is not available on this server. "
            "Install/use a pgvector-enabled PostgreSQL distribution before running UAT/prod migrations "
            "(for Docker use pgvector/pgvector:pg16)."
        )

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # If an early SQLAlchemy metadata-created DB has a JSONB compatibility column
    # called embedding_vector, replace it with the real pgvector column. The
    # canonical JSONB audit copy remains in vector_embedding.embedding.
    conn.execute(
        sa.text(
            """
            DO $$
            DECLARE
                existing_udt text;
            BEGIN
                SELECT udt_name INTO existing_udt
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'vector_embedding'
                  AND column_name = 'embedding_vector';

                IF existing_udt IS NULL THEN
                    EXECUTE 'ALTER TABLE vector_embedding ADD COLUMN embedding_vector vector(768)';
                ELSIF existing_udt <> 'vector' THEN
                    EXECUTE 'ALTER TABLE vector_embedding DROP COLUMN embedding_vector';
                    EXECUTE 'ALTER TABLE vector_embedding ADD COLUMN embedding_vector vector(768)';
                ELSE
                    EXECUTE 'ALTER TABLE vector_embedding ALTER COLUMN embedding_vector TYPE vector(768)';
                END IF;
            END $$;
            """
        )
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vector_embedding_embedding_vector_cosine
        ON vector_embedding
        USING ivfflat (embedding_vector vector_cosine_ops)
        WITH (lists = 100)
        WHERE embedding_vector IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE embedding_model
        SET pgvector_enabled = true,
            model_metadata = COALESCE(model_metadata, '{}'::jsonb)
              || jsonb_build_object(
                    'pgvector_required', true,
                    'pgvector_extension_available', true,
                    'pgvector_extension_installed', true,
                    'vector_dimensions', 768
                 )
        WHERE status = 'active'
        """
    )

    op.execute(
        """
        UPDATE vector_embedding
        SET storage_backend = 'pending_reindex',
            embedding_vector = NULL
        WHERE storage_backend <> 'pending_reindex'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_vector_embedding_embedding_vector_cosine")
    op.execute("ALTER TABLE vector_embedding DROP COLUMN IF EXISTS embedding_vector")
    op.execute(
        """
        UPDATE embedding_model
        SET pgvector_enabled = false,
            model_metadata = COALESCE(model_metadata, '{}'::jsonb)
              || jsonb_build_object('pgvector_required', false)
        """
    )
