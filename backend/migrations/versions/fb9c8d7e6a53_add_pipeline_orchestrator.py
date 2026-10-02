"""add pipeline orchestrator

Revision ID: fb9c8d7e6a53
Revises: fa8b7c6d5e42
Create Date: 2026-06-17 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fb9c8d7e6a53"
down_revision: Union[str, Sequence[str], None] = "fa8b7c6d5e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_run",
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("triggered_by", sa.String(length=100), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["triggered_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("pipeline_run_id"),
    )
    op.create_index("ix_pipeline_run_pipeline_key", "pipeline_run", ["pipeline_key"])
    op.create_index("ix_pipeline_run_status", "pipeline_run", ["status"])
    op.create_index("ix_pipeline_run_triggered_by", "pipeline_run", ["triggered_by"])
    op.create_index("idx_pipeline_run_key_status", "pipeline_run", ["pipeline_key", "status"])
    op.create_index("idx_pipeline_run_created", "pipeline_run", ["created_at"])

    op.create_table(
        "pipeline_stage_run",
        sa.Column("stage_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_key", sa.String(length=120), nullable=False),
        sa.Column("stage_name", sa.String(length=255), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_run.pipeline_run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("stage_run_id"),
    )
    op.create_index("ix_pipeline_stage_run_pipeline_run_id", "pipeline_stage_run", ["pipeline_run_id"])
    op.create_index("ix_pipeline_stage_run_stage_key", "pipeline_stage_run", ["stage_key"])
    op.create_index("ix_pipeline_stage_run_status", "pipeline_stage_run", ["status"])
    op.create_index(
        "idx_pipeline_stage_run_pipeline_sequence",
        "pipeline_stage_run",
        ["pipeline_run_id", "sequence_number"],
    )
    op.create_index("idx_pipeline_stage_run_key_status", "pipeline_stage_run", ["stage_key", "status"])


def downgrade() -> None:
    op.drop_index("idx_pipeline_stage_run_key_status", table_name="pipeline_stage_run")
    op.drop_index("idx_pipeline_stage_run_pipeline_sequence", table_name="pipeline_stage_run")
    op.drop_index("ix_pipeline_stage_run_status", table_name="pipeline_stage_run")
    op.drop_index("ix_pipeline_stage_run_stage_key", table_name="pipeline_stage_run")
    op.drop_index("ix_pipeline_stage_run_pipeline_run_id", table_name="pipeline_stage_run")
    op.drop_table("pipeline_stage_run")
    op.drop_index("idx_pipeline_run_created", table_name="pipeline_run")
    op.drop_index("idx_pipeline_run_key_status", table_name="pipeline_run")
    op.drop_index("ix_pipeline_run_triggered_by", table_name="pipeline_run")
    op.drop_index("ix_pipeline_run_status", table_name="pipeline_run")
    op.drop_index("ix_pipeline_run_pipeline_key", table_name="pipeline_run")
    op.drop_table("pipeline_run")
