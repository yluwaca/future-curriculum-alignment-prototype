"""add ingestion resilience

Revision ID: ffb3d5e7a920
Revises: ffa2c4d6e810
Create Date: 2026-06-18 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ffb3d5e7a920"
down_revision: Union[str, Sequence[str], None] = "ffa2c4d6e810"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("data_source", sa.Column("retry_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("data_source", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("data_source", sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("data_source", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("data_source", sa.Column("circuit_state", sa.String(length=50), nullable=False, server_default="closed"))
    op.add_column("data_source", sa.Column("circuit_open_until", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("data_source", "retry_policy", server_default=None)
    op.alter_column("data_source", "consecutive_failures", server_default=None)
    op.alter_column("data_source", "circuit_state", server_default=None)
    op.create_index(op.f("ix_data_source_circuit_state"), "data_source", ["circuit_state"], unique=False)
    op.create_index("idx_datasource_circuit_state", "data_source", ["circuit_state", "circuit_open_until"], unique=False)
    op.get_bind().execute(
        sa.text(
            """
            UPDATE data_source
            SET retry_policy = CASE
                WHEN connector_type = 'curriculum_pdf_upload' THEN
                    '{"max_attempts": 2, "initial_backoff_seconds": 60, "backoff_multiplier": 2, "max_backoff_seconds": 900, "open_circuit_after_failures": 5, "circuit_open_seconds": 1800}'::jsonb
                WHEN connector_type = 'statssa_qlfs_pdf' THEN
                    '{"max_attempts": 3, "initial_backoff_seconds": 300, "backoff_multiplier": 2, "max_backoff_seconds": 21600, "open_circuit_after_failures": 5, "circuit_open_seconds": 3600}'::jsonb
                ELSE
                    '{"max_attempts": 3, "initial_backoff_seconds": 300, "backoff_multiplier": 2, "max_backoff_seconds": 86400, "open_circuit_after_failures": 5, "circuit_open_seconds": 3600}'::jsonb
            END
            WHERE retry_policy = '{}'::jsonb
            """
        )
    )

    op.add_column("ingestion_job", sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("ingestion_job", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("ingestion_job", sa.Column("retry_of_job_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ingestion_job", sa.Column("failure_category", sa.String(length=100), nullable=True))
    op.add_column("ingestion_job", sa.Column("failure_stage", sa.String(length=100), nullable=True))
    op.add_column("ingestion_job", sa.Column("failure_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("ingestion_job", sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ingestion_job", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("ingestion_job", "attempt_number", server_default=None)
    op.alter_column("ingestion_job", "max_attempts", server_default=None)
    op.alter_column("ingestion_job", "failure_details", server_default=None)
    op.alter_column("ingestion_job", "retry_backoff_seconds", server_default=None)
    op.create_foreign_key(
        "fk_ingestion_job_retry_of_job_id",
        "ingestion_job",
        "ingestion_job",
        ["retry_of_job_id"],
        ["job_id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_ingestion_job_retry_of_job_id"), "ingestion_job", ["retry_of_job_id"], unique=False)
    op.create_index(op.f("ix_ingestion_job_failure_category"), "ingestion_job", ["failure_category"], unique=False)
    op.create_index(op.f("ix_ingestion_job_failure_stage"), "ingestion_job", ["failure_stage"], unique=False)
    op.create_index(op.f("ix_ingestion_job_next_retry_at"), "ingestion_job", ["next_retry_at"], unique=False)
    op.create_index("idx_ingestion_job_retry_ready", "ingestion_job", ["status", "next_retry_at"], unique=False)

    op.create_table(
        "ingestion_failure_event",
        sa.Column("failure_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("failure_stage", sa.String(length=100), nullable=False),
        sa.Column("failure_category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("retryable", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diagnostic_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("failure_id"),
    )
    op.create_index(op.f("ix_ingestion_failure_event_job_id"), "ingestion_failure_event", ["job_id"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_source_id"), "ingestion_failure_event", ["source_id"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_tenant_id"), "ingestion_failure_event", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_failure_stage"), "ingestion_failure_event", ["failure_stage"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_failure_category"), "ingestion_failure_event", ["failure_category"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_severity"), "ingestion_failure_event", ["severity"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_retryable"), "ingestion_failure_event", ["retryable"], unique=False)
    op.create_index(op.f("ix_ingestion_failure_event_next_retry_at"), "ingestion_failure_event", ["next_retry_at"], unique=False)
    op.create_index("idx_ingestion_failure_source_time", "ingestion_failure_event", ["source_id", "event_time"], unique=False)
    op.create_index("idx_ingestion_failure_category_stage", "ingestion_failure_event", ["failure_category", "failure_stage"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_ingestion_failure_category_stage", table_name="ingestion_failure_event")
    op.drop_index("idx_ingestion_failure_source_time", table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_next_retry_at"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_retryable"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_severity"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_failure_category"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_failure_stage"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_tenant_id"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_source_id"), table_name="ingestion_failure_event")
    op.drop_index(op.f("ix_ingestion_failure_event_job_id"), table_name="ingestion_failure_event")
    op.drop_table("ingestion_failure_event")

    op.drop_index("idx_ingestion_job_retry_ready", table_name="ingestion_job")
    op.drop_index(op.f("ix_ingestion_job_next_retry_at"), table_name="ingestion_job")
    op.drop_index(op.f("ix_ingestion_job_failure_stage"), table_name="ingestion_job")
    op.drop_index(op.f("ix_ingestion_job_failure_category"), table_name="ingestion_job")
    op.drop_index(op.f("ix_ingestion_job_retry_of_job_id"), table_name="ingestion_job")
    op.drop_constraint("fk_ingestion_job_retry_of_job_id", "ingestion_job", type_="foreignkey")
    op.drop_column("ingestion_job", "next_retry_at")
    op.drop_column("ingestion_job", "retry_backoff_seconds")
    op.drop_column("ingestion_job", "failure_details")
    op.drop_column("ingestion_job", "failure_stage")
    op.drop_column("ingestion_job", "failure_category")
    op.drop_column("ingestion_job", "retry_of_job_id")
    op.drop_column("ingestion_job", "max_attempts")
    op.drop_column("ingestion_job", "attempt_number")

    op.drop_index("idx_datasource_circuit_state", table_name="data_source")
    op.drop_index(op.f("ix_data_source_circuit_state"), table_name="data_source")
    op.drop_column("data_source", "circuit_open_until")
    op.drop_column("data_source", "circuit_state")
    op.drop_column("data_source", "consecutive_failures")
    op.drop_column("data_source", "last_failure_at")
    op.drop_column("data_source", "last_success_at")
    op.drop_column("data_source", "retry_policy")
