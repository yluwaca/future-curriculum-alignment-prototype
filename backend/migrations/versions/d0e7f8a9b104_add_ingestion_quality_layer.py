"""add ingestion quality layer

Revision ID: d0e7f8a9b104
Revises: c9d6e1f2a830
Create Date: 2026-06-16 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d0e7f8a9b104"
down_revision: Union[str, Sequence[str], None] = "c9d6e1f2a830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_contract",
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("record_type", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cleaning_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contract_id"),
        sa.UniqueConstraint(
            "source_id",
            "contract_key",
            "version",
            name="uq_ingestion_contract_source_key_version",
        ),
    )
    op.create_index(op.f("ix_ingestion_contract_source_id"), "ingestion_contract", ["source_id"], unique=False)
    op.create_index(op.f("ix_ingestion_contract_contract_key"), "ingestion_contract", ["contract_key"], unique=False)
    op.create_index(op.f("ix_ingestion_contract_record_type"), "ingestion_contract", ["record_type"], unique=False)
    op.create_index(op.f("ix_ingestion_contract_status"), "ingestion_contract", ["status"], unique=False)
    op.create_index("idx_ingestion_contract_record_type", "ingestion_contract", ["source_id", "record_type"], unique=False)

    op.create_table(
        "data_quality_rule",
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_key", sa.String(length=150), nullable=False),
        sa.Column("rule_type", sa.String(length=100), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=True),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("expectation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["ingestion_contract.contract_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_index(op.f("ix_data_quality_rule_contract_id"), "data_quality_rule", ["contract_id"], unique=False)
    op.create_index(op.f("ix_data_quality_rule_rule_key"), "data_quality_rule", ["rule_key"], unique=False)
    op.create_index(op.f("ix_data_quality_rule_rule_type"), "data_quality_rule", ["rule_type"], unique=False)
    op.create_index(op.f("ix_data_quality_rule_severity"), "data_quality_rule", ["severity"], unique=False)
    op.create_index(op.f("ix_data_quality_rule_is_active"), "data_quality_rule", ["is_active"], unique=False)
    op.create_index("idx_data_quality_rule_contract_key", "data_quality_rule", ["contract_id", "rule_key"], unique=False)

    op.create_table(
        "data_quality_check",
        sa.Column("check_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("check_scope", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("observed_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("check_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["ingestion_contract.contract_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["data_quality_rule.rule_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("check_id"),
    )
    op.create_index(op.f("ix_data_quality_check_job_id"), "data_quality_check", ["job_id"], unique=False)
    op.create_index(op.f("ix_data_quality_check_source_id"), "data_quality_check", ["source_id"], unique=False)
    op.create_index(op.f("ix_data_quality_check_raw_record_id"), "data_quality_check", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_data_quality_check_contract_id"), "data_quality_check", ["contract_id"], unique=False)
    op.create_index(op.f("ix_data_quality_check_rule_id"), "data_quality_check", ["rule_id"], unique=False)
    op.create_index(op.f("ix_data_quality_check_check_scope"), "data_quality_check", ["check_scope"], unique=False)
    op.create_index(op.f("ix_data_quality_check_status"), "data_quality_check", ["status"], unique=False)
    op.create_index(op.f("ix_data_quality_check_severity"), "data_quality_check", ["severity"], unique=False)
    op.create_index("idx_data_quality_check_job_status", "data_quality_check", ["job_id", "status"], unique=False)
    op.create_index("idx_data_quality_check_record_status", "data_quality_check", ["raw_record_id", "status"], unique=False)

    op.create_table(
        "cleaned_ingestion_record",
        sa.Column("cleaned_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contract_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cleaning_status", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("cleaned_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cleaning_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["ingestion_contract.contract_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("cleaned_record_id"),
        sa.UniqueConstraint("raw_record_id", "content_hash", name="uq_cleaned_record_raw_hash"),
    )
    op.create_index(op.f("ix_cleaned_ingestion_record_raw_record_id"), "cleaned_ingestion_record", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_job_id"), "cleaned_ingestion_record", ["job_id"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_source_id"), "cleaned_ingestion_record", ["source_id"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_contract_id"), "cleaned_ingestion_record", ["contract_id"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_cleaning_status"), "cleaned_ingestion_record", ["cleaning_status"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_content_hash"), "cleaned_ingestion_record", ["content_hash"], unique=False)
    op.create_index("idx_cleaned_record_job_status", "cleaned_ingestion_record", ["job_id", "cleaning_status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_cleaned_record_job_status", table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_content_hash"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_cleaning_status"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_contract_id"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_source_id"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_job_id"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_raw_record_id"), table_name="cleaned_ingestion_record")
    op.drop_table("cleaned_ingestion_record")

    op.drop_index("idx_data_quality_check_record_status", table_name="data_quality_check")
    op.drop_index("idx_data_quality_check_job_status", table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_severity"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_status"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_check_scope"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_rule_id"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_contract_id"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_raw_record_id"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_source_id"), table_name="data_quality_check")
    op.drop_index(op.f("ix_data_quality_check_job_id"), table_name="data_quality_check")
    op.drop_table("data_quality_check")

    op.drop_index("idx_data_quality_rule_contract_key", table_name="data_quality_rule")
    op.drop_index(op.f("ix_data_quality_rule_is_active"), table_name="data_quality_rule")
    op.drop_index(op.f("ix_data_quality_rule_severity"), table_name="data_quality_rule")
    op.drop_index(op.f("ix_data_quality_rule_rule_type"), table_name="data_quality_rule")
    op.drop_index(op.f("ix_data_quality_rule_rule_key"), table_name="data_quality_rule")
    op.drop_index(op.f("ix_data_quality_rule_contract_id"), table_name="data_quality_rule")
    op.drop_table("data_quality_rule")

    op.drop_index("idx_ingestion_contract_record_type", table_name="ingestion_contract")
    op.drop_index(op.f("ix_ingestion_contract_status"), table_name="ingestion_contract")
    op.drop_index(op.f("ix_ingestion_contract_record_type"), table_name="ingestion_contract")
    op.drop_index(op.f("ix_ingestion_contract_contract_key"), table_name="ingestion_contract")
    op.drop_index(op.f("ix_ingestion_contract_source_id"), table_name="ingestion_contract")
    op.drop_table("ingestion_contract")
