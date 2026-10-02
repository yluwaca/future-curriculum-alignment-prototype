"""
Upgrade vector embeddings from 384-dim to 768-dim.
Adds new 768-dim embedding models and migrates column type.
"""
from __future__ import annotations

import uuid
from typing import List, Optional, Tuple

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "1a2b3c4d5e01"
down_revision = "e5c1a7b9d204"
branch_labels = None
depends_on = None


OLD_DIM = 384
NEW_DIM = 768


def upgrade():
    conn = op.get_bind()

    # 1. Update local_hashing model to 768-dim (v2)
    conn.execute(
        sa.text(
            """
            UPDATE embedding_model
            SET dimensions = :new_dim,
                model_version = '2',
                model_name = 'Deterministic Hashing Embeddings (768-dim)',
                description = 'Local deterministic fallback embedding provider (768-dim).'
            WHERE model_key = 'local_hashing_384_v1'
            """
        ),
        {"new_dim": NEW_DIM},
    )

    # 2. Update model_key to reflect new dimension
    conn.execute(
        sa.text(
            """
            UPDATE embedding_model
            SET model_key = 'local_hashing_768_v1'
            WHERE model_key = 'local_hashing_384_v1'
            """
        )
    )

    # 3. Insert or update the sentence-transformer model (all-mpnet-base-v2, 768-dim)
    existing_st = conn.execute(
        sa.text(
            "SELECT model_id FROM embedding_model WHERE model_key = 'sentence_all-MiniLM-L6-v2_384_v1'"
        )
    ).fetchone()
    if existing_st:
        conn.execute(
            sa.text(
                """
                UPDATE embedding_model
                SET model_key = 'sentence_all-mpnet-base-v2_768_v1',
                    model_name = 'sentence-transformers/all-mpnet-base-v2',
                    dimensions = :dim,
                    description = 'Sentence-transformer all-mpnet-base-v2 embeddings (768-dim).'
                WHERE model_key = 'sentence_all-MiniLM-L6-v2_384_v1'
                """
            ),
            {"dim": NEW_DIM},
        )
    else:
        conn.execute(
            sa.text(
                """
                INSERT INTO embedding_model (
                    model_id, model_key, provider, model_name, model_version,
                    dimensions, distance_metric, status, is_default, pgvector_enabled,
                    description, model_metadata
                ) VALUES (
                    '00000000-0000-4000-8000-000000000302',
                    'sentence_all-mpnet-base-v2_768_v1',
                    'sentence-transformers',
                    'sentence-transformers/all-mpnet-base-v2',
                    '1',
                    :dim,
                    'cosine',
                    'active',
                    true,
                    false,
                    'Sentence-transformer all-mpnet-base-v2 embeddings (768-dim).',
                    jsonb_build_object('purpose', 'semantic', 'requires_external_model', true)
                )
                ON CONFLICT (model_key) DO NOTHING
                """
            ),
            {"dim": NEW_DIM},
        )

    has_embedding_vector = conn.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'vector_embedding'
                  AND column_name = 'embedding_vector'
            )
            """
        )
    ).scalar()

    # 4. Clear existing JSONB embeddings (they are 384-dim and incompatible with 768).
    #    The optional pgvector column only exists when the PostgreSQL server has
    #    the vector extension installed, so clean installs without pgvector must
    #    not reference it.
    if has_embedding_vector:
        conn.execute(
            sa.text(
                """
                UPDATE vector_embedding
                SET embedding_vector = NULL,
                    embedding = '[]'::jsonb,
                    embedding_text = NULL,
                    storage_backend = 'pending_reindex'
                WHERE storage_backend != 'pending_reindex'
                """
            )
        )
    else:
        conn.execute(
            sa.text(
                """
                UPDATE vector_embedding
                SET embedding = '[]'::jsonb,
                    embedding_text = NULL,
                    storage_backend = 'pending_reindex'
                WHERE storage_backend != 'pending_reindex'
                """
            )
        )

    if not has_embedding_vector:
        return

    # 5. Alter pgvector column from vector(384) to vector(768)
    #    pgvector requires column to be empty (or have compatible data) to ALTER TYPE.
    conn.execute(
        sa.text(
            """
            ALTER TABLE vector_embedding
            ALTER COLUMN embedding_vector TYPE vector(768)
            """
        )
    )


def downgrade():
    conn = op.get_bind()

    # Clear vectors first (384/768 mismatch)
    conn.execute(
        sa.text(
            """
            UPDATE vector_embedding
            SET embedding_vector = NULL,
                embedding = '[]'::jsonb,
                embedding_text = NULL
            """
        )
    )

    # Revert column to 384
    conn.execute(
        sa.text(
            """
            ALTER TABLE vector_embedding
            ALTER COLUMN embedding_vector TYPE vector(384)
            """
        )
    )

    # Revert model keys
    conn.execute(
        sa.text(
            """
            UPDATE embedding_model
            SET model_key = 'local_hashing_384_v1',
                model_version = '1',
                dimensions = 384,
                model_name = 'Deterministic Hashing Embeddings',
                description = 'Local deterministic fallback embedding provider.'
            WHERE model_key = 'local_hashing_768_v1'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE embedding_model
            SET model_key = 'sentence_all-MiniLM-L6-v2_384_v1',
                model_name = 'sentence-transformers/all-MiniLM-L6-v2',
                dimensions = 384,
                description = 'Sentence-transformer all-MiniLM-L6-v2 embeddings.'
            WHERE model_key = 'sentence_all-mpnet-base-v2_768_v1'
            """
        )
    )

    # Clear re-indexed embeddings
    conn.execute(
        sa.text(
            """
            UPDATE vector_embedding
            SET embedding = '[]'::jsonb,
                embedding_text = NULL,
                storage_backend = 'pending_reindex'
            """
        )
    )
