"""add tenant foundation

Revision ID: fe3a6b8c9d12
Revises: fd2e4f6a8b10
Create Date: 2026-06-18 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fe3a6b8c9d12"
down_revision: Union[str, Sequence[str], None] = "fd2e4f6a8b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tenant_type", sa.String(length=80), nullable=False),
        sa.Column("country", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tenant_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.UniqueConstraint("tenant_key"),
    )
    op.create_index(op.f("ix_tenant_tenant_key"), "tenant", ["tenant_key"], unique=True)
    op.create_index(op.f("ix_tenant_name"), "tenant", ["name"], unique=False)
    op.create_index(op.f("ix_tenant_tenant_type"), "tenant", ["tenant_type"], unique=False)
    op.create_index(op.f("ix_tenant_country"), "tenant", ["country"], unique=False)
    op.create_index(op.f("ix_tenant_region"), "tenant", ["region"], unique=False)
    op.create_index(op.f("ix_tenant_status"), "tenant", ["status"], unique=False)
    op.create_index("idx_tenant_status_type", "tenant", ["status", "tenant_type"], unique=False)

    add_tenant_column("data_source")
    op.add_column("data_source", sa.Column("source_scope", sa.String(length=50), nullable=False, server_default="shared"))
    op.alter_column("data_source", "source_scope", server_default=None)
    op.create_index(op.f("ix_data_source_tenant_id"), "data_source", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_data_source_source_scope"), "data_source", ["source_scope"], unique=False)
    op.create_index("idx_datasource_tenant_scope", "data_source", ["tenant_id", "source_scope"], unique=False)

    for table_name in (
        "ingestion_job",
        "raw_ingestion_record",
        "cleaned_ingestion_record",
        "curriculum_document",
        "curriculum_document_version",
        "document_chunk",
        "pipeline_run",
    ):
        add_tenant_column(table_name)

    op.add_column("pipeline_run", sa.Column("run_scope", sa.String(length=50), nullable=False, server_default="shared"))
    op.alter_column("pipeline_run", "run_scope", server_default=None)
    op.create_index(op.f("ix_pipeline_run_run_scope"), "pipeline_run", ["run_scope"], unique=False)

    op.execute(
        """
        UPDATE ingestion_job job
        SET tenant_id = source.tenant_id
        FROM data_source source
        WHERE job.source_id = source.source_id
          AND job.tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE raw_ingestion_record record
        SET tenant_id = job.tenant_id
        FROM ingestion_job job
        WHERE record.job_id = job.job_id
          AND record.tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE cleaned_ingestion_record record
        SET tenant_id = job.tenant_id
        FROM ingestion_job job
        WHERE record.job_id = job.job_id
          AND record.tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE curriculum_document_version version
        SET tenant_id = doc.tenant_id
        FROM curriculum_document doc
        WHERE version.document_id = doc.document_id
          AND version.tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE document_chunk chunk
        SET tenant_id = version.tenant_id
        FROM curriculum_document_version version
        WHERE chunk.version_id = version.version_id
          AND chunk.tenant_id IS NULL
        """
    )

    op.create_index("idx_ingestion_job_tenant_status", "ingestion_job", ["tenant_id", "status"], unique=False)
    op.create_index("idx_raw_record_tenant_type", "raw_ingestion_record", ["tenant_id", "record_type"], unique=False)
    op.create_index("idx_cleaned_record_tenant_status", "cleaned_ingestion_record", ["tenant_id", "cleaning_status"], unique=False)
    op.create_index("idx_curriculum_document_tenant_status", "curriculum_document", ["tenant_id", "status"], unique=False)
    op.create_index("idx_document_chunk_tenant_version", "document_chunk", ["tenant_id", "version_id"], unique=False)
    op.create_index("idx_pipeline_run_tenant_status", "pipeline_run", ["tenant_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_pipeline_run_tenant_status", table_name="pipeline_run")
    op.drop_index("idx_document_chunk_tenant_version", table_name="document_chunk")
    op.drop_index("idx_curriculum_document_tenant_status", table_name="curriculum_document")
    op.drop_index("idx_cleaned_record_tenant_status", table_name="cleaned_ingestion_record")
    op.drop_index("idx_raw_record_tenant_type", table_name="raw_ingestion_record")
    op.drop_index("idx_ingestion_job_tenant_status", table_name="ingestion_job")

    op.drop_index(op.f("ix_pipeline_run_run_scope"), table_name="pipeline_run")
    op.drop_column("pipeline_run", "run_scope")

    for table_name in (
        "pipeline_run",
        "document_chunk",
        "curriculum_document_version",
        "curriculum_document",
        "cleaned_ingestion_record",
        "raw_ingestion_record",
        "ingestion_job",
    ):
        drop_tenant_column(table_name)

    op.drop_index("idx_datasource_tenant_scope", table_name="data_source")
    op.drop_index(op.f("ix_data_source_source_scope"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_tenant_id"), table_name="data_source")
    op.drop_column("data_source", "source_scope")
    drop_tenant_column("data_source")

    op.drop_index("idx_tenant_status_type", table_name="tenant")
    op.drop_index(op.f("ix_tenant_status"), table_name="tenant")
    op.drop_index(op.f("ix_tenant_region"), table_name="tenant")
    op.drop_index(op.f("ix_tenant_country"), table_name="tenant")
    op.drop_index(op.f("ix_tenant_tenant_type"), table_name="tenant")
    op.drop_index(op.f("ix_tenant_name"), table_name="tenant")
    op.drop_index(op.f("ix_tenant_tenant_key"), table_name="tenant")
    op.drop_table("tenant")


def add_tenant_column(table_name: str) -> None:
    op.add_column(table_name, sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        f"fk_{table_name}_tenant_id",
        table_name,
        "tenant",
        ["tenant_id"],
        ["tenant_id"],
        ondelete="SET NULL",
    )


def drop_tenant_column(table_name: str) -> None:
    op.drop_constraint(f"fk_{table_name}_tenant_id", table_name, type_="foreignkey")
    op.drop_column(table_name, "tenant_id")
