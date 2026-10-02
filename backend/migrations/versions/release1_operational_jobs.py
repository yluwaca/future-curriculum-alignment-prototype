"""add durable operational job queue

Revision ID: release1_operational_jobs
Revises: phase7_model_registry
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "release1_operational_jobs"
down_revision: Union[str, Sequence[str], None] = "phase7_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_job",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=120), nullable=False),
        sa.Column("queue_name", sa.String(length=80), nullable=False, server_default="default"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("progress_message", sa.String(length=500), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_of_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("run_manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=180), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_operational_job_job_type", "operational_job", ["job_type"])
    op.create_index("ix_operational_job_queue_name", "operational_job", ["queue_name"])
    op.create_index("ix_operational_job_status", "operational_job", ["status"])
    op.create_index("ix_operational_job_idempotency_key", "operational_job", ["idempotency_key"], unique=True)
    op.create_index("ix_operational_job_requested_by", "operational_job", ["requested_by"])
    op.create_index("ix_operational_job_retry_of_job_id", "operational_job", ["retry_of_job_id"])
    op.create_index("ix_operational_job_heartbeat_at", "operational_job", ["heartbeat_at"])
    op.create_index("ix_operational_job_next_attempt_at", "operational_job", ["next_attempt_at"])
    op.create_index("idx_operational_job_claim", "operational_job", ["status", "next_attempt_at"])
    op.create_index("idx_operational_job_type_status", "operational_job", ["job_type", "status"])


def downgrade() -> None:
    op.drop_table("operational_job")
