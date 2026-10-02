"""add model registry for lifecycle management

Revision ID: phase7_model_registry
Revises: phase3_dataset_snapshots
Create Date: 2026-07-27 16:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "phase7_model_registry"
down_revision: Union[str, Sequence[str], None] = "phase3_dataset_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_type", sa.String(length=50), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column("artifact_path", sa.String(length=500), nullable=False),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=True),
        sa.Column("artifact_checksum", sa.String(length=64), nullable=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dataset_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cv_folds", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("baseline_comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fairness_assessment", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("explainability", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("promotion_gates", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("model_card", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("promoted_by", sa.String(length=100), nullable=True),
        sa.Column("rejected_by", sa.String(length=100), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    op.create_index("ix_model_registry_model_type", "model_registry", ["model_type"], unique=False)
    op.create_index("ix_model_registry_model_version", "model_registry", ["model_version"], unique=False)
    op.create_index("ix_model_registry_lifecycle_state", "model_registry", ["lifecycle_state"], unique=False)
    op.create_index("ix_model_registry_snapshot_id", "model_registry", ["snapshot_id"], unique=False)
    op.create_index("ix_model_registry_is_active", "model_registry", ["is_active"], unique=False)
    op.create_index("idx_model_registry_type_state", "model_registry", ["model_type", "lifecycle_state"], unique=False)
    op.create_index("idx_model_registry_active", "model_registry", ["model_type", "is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_model_registry_active", table_name="model_registry")
    op.drop_index("idx_model_registry_type_state", table_name="model_registry")
    op.drop_index("ix_model_registry_is_active", table_name="model_registry")
    op.drop_index("ix_model_registry_snapshot_id", table_name="model_registry")
    op.drop_index("ix_model_registry_lifecycle_state", table_name="model_registry")
    op.drop_index("ix_model_registry_model_version", table_name="model_registry")
    op.drop_index("ix_model_registry_model_type", table_name="model_registry")
    op.drop_table("model_registry")
