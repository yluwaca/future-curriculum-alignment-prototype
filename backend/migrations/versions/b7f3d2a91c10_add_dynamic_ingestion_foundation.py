"""add dynamic ingestion foundation

Revision ID: b7f3d2a91c10
Revises: 91de4aeb6905
Create Date: 2026-06-16 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b7f3d2a91c10"
down_revision: Union[str, Sequence[str], None] = "91de4aeb6905"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_source",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_category", sa.String(length=50), nullable=False),
        sa.Column("connector_type", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("storage_path", sa.String(length=1000), nullable=True),
        sa.Column("refresh_policy", sa.String(length=50), nullable=True),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("is_authorised", sa.Boolean(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("auth_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("source_key"),
    )
    op.create_index(op.f("ix_data_source_source_key"), "data_source", ["source_key"], unique=True)
    op.create_index(op.f("ix_data_source_source_type"), "data_source", ["source_type"], unique=False)
    op.create_index(op.f("ix_data_source_source_category"), "data_source", ["source_category"], unique=False)
    op.create_index(op.f("ix_data_source_connector_type"), "data_source", ["connector_type"], unique=False)
    op.create_index(op.f("ix_data_source_status"), "data_source", ["status"], unique=False)
    op.create_index(op.f("ix_data_source_is_authorised"), "data_source", ["is_authorised"], unique=False)
    op.create_index("idx_datasource_category_type", "data_source", ["source_category", "source_type"], unique=False)
    op.create_index("idx_datasource_authorised_status", "data_source", ["is_authorised", "status"], unique=False)

    op.create_table(
        "ingestion_job",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("triggered_by", sa.String(length=100), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_loaded", sa.Integer(), nullable=False),
        sa.Column("records_failed", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["triggered_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(op.f("ix_ingestion_job_source_id"), "ingestion_job", ["source_id"], unique=False)
    op.create_index(op.f("ix_ingestion_job_job_type"), "ingestion_job", ["job_type"], unique=False)
    op.create_index(op.f("ix_ingestion_job_status"), "ingestion_job", ["status"], unique=False)
    op.create_index(op.f("ix_ingestion_job_triggered_by"), "ingestion_job", ["triggered_by"], unique=False)
    op.create_index("idx_ingestion_job_status_type", "ingestion_job", ["status", "job_type"], unique=False)
    op.create_index("idx_ingestion_job_source_status", "ingestion_job", ["source_id", "status"], unique=False)
    op.create_index("idx_ingestion_job_created", "ingestion_job", ["created_at"], unique=False)

    op.create_table(
        "raw_ingestion_record",
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("record_type", sa.String(length=100), nullable=False),
        sa.Column("storage_uri", sa.String(length=1000), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("validation_status", sa.String(length=50), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalised_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index(op.f("ix_raw_ingestion_record_job_id"), "raw_ingestion_record", ["job_id"], unique=False)
    op.create_index(op.f("ix_raw_ingestion_record_source_id"), "raw_ingestion_record", ["source_id"], unique=False)
    op.create_index(op.f("ix_raw_ingestion_record_source_record_id"), "raw_ingestion_record", ["source_record_id"], unique=False)
    op.create_index(op.f("ix_raw_ingestion_record_record_type"), "raw_ingestion_record", ["record_type"], unique=False)
    op.create_index(op.f("ix_raw_ingestion_record_content_hash"), "raw_ingestion_record", ["content_hash"], unique=False)
    op.create_index(op.f("ix_raw_ingestion_record_validation_status"), "raw_ingestion_record", ["validation_status"], unique=False)
    op.create_index("idx_raw_record_job_type", "raw_ingestion_record", ["job_id", "record_type"], unique=False)
    op.create_index("idx_raw_record_source_hash", "raw_ingestion_record", ["source_id", "content_hash"], unique=False)

    op.create_table(
        "data_lineage_event",
        sa.Column("lineage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("output_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_system", sa.String(length=255), nullable=False),
        sa.Column("processing_stage", sa.String(length=100), nullable=False),
        sa.Column("transformation_description", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["input_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["output_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("lineage_id"),
    )
    op.create_index(op.f("ix_data_lineage_event_event_time"), "data_lineage_event", ["event_time"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_job_id"), "data_lineage_event", ["job_id"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_source_id"), "data_lineage_event", ["source_id"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_input_record_id"), "data_lineage_event", ["input_record_id"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_output_record_id"), "data_lineage_event", ["output_record_id"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_processing_stage"), "data_lineage_event", ["processing_stage"], unique=False)
    op.create_index(op.f("ix_data_lineage_event_actor_id"), "data_lineage_event", ["actor_id"], unique=False)
    op.create_index("idx_lineage_job_stage", "data_lineage_event", ["job_id", "processing_stage"], unique=False)
    op.create_index("idx_lineage_source_stage", "data_lineage_event", ["source_id", "processing_stage"], unique=False)

    op.create_table(
        "lmi_indicator",
        sa.Column("id_indicator", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id_indicator"),
    )
    op.create_index(op.f("ix_lmi_indicator_id_indicator"), "lmi_indicator", ["id_indicator"], unique=False)

    op.create_table(
        "lmi_observation",
        sa.Column("id_observation", sa.Integer(), nullable=False),
        sa.Column("indicator_id", sa.Integer(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source_file", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["indicator_id"], ["lmi_indicator.id_indicator"]),
        sa.PrimaryKeyConstraint("id_observation"),
    )
    op.create_index(op.f("ix_lmi_observation_id_observation"), "lmi_observation", ["id_observation"], unique=False)

    op.execute(
        """
        INSERT INTO data_source (
            source_id, source_key, name, source_type, source_category,
            connector_type, base_url, storage_path, refresh_policy, owner,
            status, is_authorised, config, auth_config
        )
        VALUES (
            '00000000-0000-4000-8000-000000000101', 'statssa_qlfs', 'StatsSA Quarterly Labour Force Survey',
            'api_pdf', 'labour_market', 'statssa_qlfs',
            'https://www.statssa.gov.za/publications/P0211/',
            'data/raw/statssa', 'manual', 'system',
            'active', true, '{}'::jsonb, '{}'::jsonb
        )
        ON CONFLICT (source_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("lmi_observation")
    op.drop_table("lmi_indicator")
    op.drop_table("data_lineage_event")
    op.drop_table("raw_ingestion_record")
    op.drop_table("ingestion_job")
    op.drop_table("data_source")
