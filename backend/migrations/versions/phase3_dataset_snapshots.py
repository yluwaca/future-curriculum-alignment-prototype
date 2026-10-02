"""add model dataset snapshots

Revision ID: phase3_dataset_snapshots
Revises: pgvector_required_01
Create Date: 2026-07-27 14:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "phase3_dataset_snapshots"
down_revision: Union[str, Sequence[str], None] = "pgvector_required_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_dataset_snapshot",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_type", sa.String(length=50), nullable=False),
        sa.Column("snapshot_version", sa.String(length=80), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("extraction_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_observation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_observation_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cleaned_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("empirical_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("simulated_records_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_tables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exclusion_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("curriculum_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("labour_market_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("feature_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("target_construction", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("split_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("leakage_checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("random_seeds", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("software_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("record_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("snapshot_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("idx_model_dataset_snapshot_type_created", "model_dataset_snapshot", ["model_type", "created_at"], unique=False)
    op.create_index("idx_model_dataset_snapshot_dates", "model_dataset_snapshot", ["min_observation_date", "max_observation_date"], unique=False)
    op.create_index("ix_model_dataset_snapshot_model_type", "model_dataset_snapshot", ["model_type"], unique=False)
    op.create_index("ix_model_dataset_snapshot_snapshot_version", "model_dataset_snapshot", ["snapshot_version"], unique=False)
    op.create_index("ix_model_dataset_snapshot_extraction_timestamp", "model_dataset_snapshot", ["extraction_timestamp"], unique=False)
    op.create_index("ix_model_dataset_snapshot_created_by", "model_dataset_snapshot", ["created_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_dataset_snapshot_created_by", table_name="model_dataset_snapshot")
    op.drop_index("ix_model_dataset_snapshot_extraction_timestamp", table_name="model_dataset_snapshot")
    op.drop_index("ix_model_dataset_snapshot_snapshot_version", table_name="model_dataset_snapshot")
    op.drop_index("ix_model_dataset_snapshot_model_type", table_name="model_dataset_snapshot")
    op.drop_index("idx_model_dataset_snapshot_dates", table_name="model_dataset_snapshot")
    op.drop_index("idx_model_dataset_snapshot_type_created", table_name="model_dataset_snapshot")
    op.drop_table("model_dataset_snapshot")

