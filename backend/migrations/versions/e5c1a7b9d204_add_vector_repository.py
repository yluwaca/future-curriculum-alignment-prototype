"""add vector repository

Revision ID: e5c1a7b9d204
Revises: d2f6b7a4c901
Create Date: 2026-06-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5c1a7b9d204"
down_revision: Union[str, Sequence[str], None] = "d2f6b7a4c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "embedding_model",
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_key", sa.String(length=150), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("distance_metric", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("pgvector_enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("model_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("model_id"),
        sa.UniqueConstraint("model_key"),
    )
    op.create_index(op.f("ix_embedding_model_model_key"), "embedding_model", ["model_key"], unique=True)
    op.create_index(op.f("ix_embedding_model_provider"), "embedding_model", ["provider"], unique=False)
    op.create_index(op.f("ix_embedding_model_status"), "embedding_model", ["status"], unique=False)
    op.create_index(op.f("ix_embedding_model_is_default"), "embedding_model", ["is_default"], unique=False)
    op.create_index("idx_embedding_model_default_status", "embedding_model", ["is_default", "status"], unique=False)

    op.create_table(
        "vector_embedding",
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_entity_type", sa.String(length=100), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding_text", sa.Text(), nullable=True),
        sa.Column("storage_backend", sa.String(length=50), nullable=False),
        sa.Column("embedding_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["embedding_model.model_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("embedding_id"),
    )
    op.create_index(op.f("ix_vector_embedding_model_id"), "vector_embedding", ["model_id"], unique=False)
    op.create_index(op.f("ix_vector_embedding_source_entity_type"), "vector_embedding", ["source_entity_type"], unique=False)
    op.create_index(op.f("ix_vector_embedding_source_entity_id"), "vector_embedding", ["source_entity_id"], unique=False)
    op.create_index(op.f("ix_vector_embedding_source_text_hash"), "vector_embedding", ["source_text_hash"], unique=False)
    op.create_index(op.f("ix_vector_embedding_storage_backend"), "vector_embedding", ["storage_backend"], unique=False)
    op.create_index("idx_vector_embedding_source_model", "vector_embedding", ["source_entity_type", "source_entity_id", "model_id"], unique=True)
    op.create_index("idx_vector_embedding_model_backend", "vector_embedding", ["model_id", "storage_backend"], unique=False)

    op.create_table(
        "semantic_search_query",
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_entity_type", sa.String(length=100), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_id"], ["embedding_model.model_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_index(op.f("ix_semantic_search_query_event_time"), "semantic_search_query", ["event_time"], unique=False)
    op.create_index(op.f("ix_semantic_search_query_actor_id"), "semantic_search_query", ["actor_id"], unique=False)
    op.create_index(op.f("ix_semantic_search_query_model_id"), "semantic_search_query", ["model_id"], unique=False)
    op.create_index(op.f("ix_semantic_search_query_source_entity_type"), "semantic_search_query", ["source_entity_type"], unique=False)
    op.create_index("idx_semantic_query_actor_time", "semantic_search_query", ["actor_id", "event_time"], unique=False)

    op.execute(
        """
        INSERT INTO embedding_model (
            model_id, model_key, provider, model_name, model_version,
            dimensions, distance_metric, status, is_default, pgvector_enabled,
            description, model_metadata
        )
        VALUES (
            '00000000-0000-4000-8000-000000000301',
            'local_hashing_384_v1',
            'local',
            'Deterministic Hashing Embeddings',
            '1',
            384,
            'cosine',
            'active',
            true,
            false,
            'Local deterministic fallback embedding provider for vector repository readiness.',
            jsonb_build_object('purpose', 'fallback', 'requires_external_model', false)
        )
        ON CONFLICT (model_key) DO NOTHING
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
                BEGIN
                    CREATE EXTENSION IF NOT EXISTS vector;
                    ALTER TABLE vector_embedding
                        ADD COLUMN IF NOT EXISTS embedding_vector vector(384);
                    UPDATE embedding_model
                    SET pgvector_enabled = true,
                        model_metadata = model_metadata || jsonb_build_object(
                            'pgvector_extension_available', true,
                            'pgvector_extension_installed', true
                        )
                    WHERE model_key = 'local_hashing_384_v1';
                EXCEPTION
                    WHEN insufficient_privilege THEN
                        UPDATE embedding_model
                        SET pgvector_enabled = false,
                            model_metadata = model_metadata || jsonb_build_object(
                                'pgvector_extension_available', true,
                                'pgvector_extension_installed', false,
                                'pgvector_install_error', 'insufficient_privilege'
                            )
                        WHERE model_key = 'local_hashing_384_v1';
                END;
            ELSE
                UPDATE embedding_model
                SET model_metadata = model_metadata || jsonb_build_object(
                    'pgvector_extension_available', false,
                    'pgvector_extension_installed', false
                )
                WHERE model_key = 'local_hashing_384_v1';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("idx_semantic_query_actor_time", table_name="semantic_search_query")
    op.drop_index(op.f("ix_semantic_search_query_source_entity_type"), table_name="semantic_search_query")
    op.drop_index(op.f("ix_semantic_search_query_model_id"), table_name="semantic_search_query")
    op.drop_index(op.f("ix_semantic_search_query_actor_id"), table_name="semantic_search_query")
    op.drop_index(op.f("ix_semantic_search_query_event_time"), table_name="semantic_search_query")
    op.drop_table("semantic_search_query")
    op.drop_index("idx_vector_embedding_model_backend", table_name="vector_embedding")
    op.drop_index("idx_vector_embedding_source_model", table_name="vector_embedding")
    op.drop_index(op.f("ix_vector_embedding_storage_backend"), table_name="vector_embedding")
    op.drop_index(op.f("ix_vector_embedding_source_text_hash"), table_name="vector_embedding")
    op.drop_index(op.f("ix_vector_embedding_source_entity_id"), table_name="vector_embedding")
    op.drop_index(op.f("ix_vector_embedding_source_entity_type"), table_name="vector_embedding")
    op.drop_index(op.f("ix_vector_embedding_model_id"), table_name="vector_embedding")
    op.drop_table("vector_embedding")
    op.drop_index("idx_embedding_model_default_status", table_name="embedding_model")
    op.drop_index(op.f("ix_embedding_model_is_default"), table_name="embedding_model")
    op.drop_index(op.f("ix_embedding_model_status"), table_name="embedding_model")
    op.drop_index(op.f("ix_embedding_model_provider"), table_name="embedding_model")
    op.drop_index(op.f("ix_embedding_model_model_key"), table_name="embedding_model")
    op.drop_table("embedding_model")
