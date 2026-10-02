"""add connector abstraction

Revision ID: ff4b7c9d0e21
Revises: fe3a6b8c9d12
Create Date: 2026-06-18 10:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ff4b7c9d0e21"
down_revision: Union[str, Sequence[str], None] = "fe3a6b8c9d12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_definition",
        sa.Column("connector_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("connector_family", sa.String(length=100), nullable=False),
        sa.Column("ingestion_mode", sa.String(length=50), nullable=False),
        sa.Column("source_category", sa.String(length=80), nullable=False),
        sa.Column("source_format", sa.String(length=80), nullable=False),
        sa.Column("normaliser_key", sa.String(length=150), nullable=True),
        sa.Column("is_streaming_capable", sa.Boolean(), nullable=False),
        sa.Column("requires_auth", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("capability_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("default_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("connector_definition_id"),
        sa.UniqueConstraint("connector_key"),
    )
    op.create_index(op.f("ix_connector_definition_connector_key"), "connector_definition", ["connector_key"], unique=True)
    op.create_index(op.f("ix_connector_definition_connector_family"), "connector_definition", ["connector_family"], unique=False)
    op.create_index(op.f("ix_connector_definition_ingestion_mode"), "connector_definition", ["ingestion_mode"], unique=False)
    op.create_index(op.f("ix_connector_definition_source_category"), "connector_definition", ["source_category"], unique=False)
    op.create_index(op.f("ix_connector_definition_source_format"), "connector_definition", ["source_format"], unique=False)
    op.create_index(op.f("ix_connector_definition_normaliser_key"), "connector_definition", ["normaliser_key"], unique=False)
    op.create_index(op.f("ix_connector_definition_is_streaming_capable"), "connector_definition", ["is_streaming_capable"], unique=False)
    op.create_index(op.f("ix_connector_definition_status"), "connector_definition", ["status"], unique=False)
    op.create_index("idx_connector_definition_family_mode", "connector_definition", ["connector_family", "ingestion_mode"], unique=False)
    op.create_index("idx_connector_definition_category_format", "connector_definition", ["source_category", "source_format"], unique=False)

    op.add_column("data_source", sa.Column("connector_definition_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("data_source", sa.Column("ingestion_mode", sa.String(length=50), nullable=False, server_default="batch"))
    op.add_column("data_source", sa.Column("source_format", sa.String(length=80), nullable=False, server_default="unknown"))
    op.add_column("data_source", sa.Column("normaliser_key", sa.String(length=150), nullable=True))
    op.alter_column("data_source", "ingestion_mode", server_default=None)
    op.alter_column("data_source", "source_format", server_default=None)
    op.create_foreign_key(
        "fk_data_source_connector_definition_id",
        "data_source",
        "connector_definition",
        ["connector_definition_id"],
        ["connector_definition_id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_data_source_connector_definition_id"), "data_source", ["connector_definition_id"], unique=False)
    op.create_index(op.f("ix_data_source_ingestion_mode"), "data_source", ["ingestion_mode"], unique=False)
    op.create_index(op.f("ix_data_source_source_format"), "data_source", ["source_format"], unique=False)
    op.create_index(op.f("ix_data_source_normaliser_key"), "data_source", ["normaliser_key"], unique=False)
    op.create_index("idx_datasource_connector_definition", "data_source", ["connector_definition_id", "status"], unique=False)
    op.create_index("idx_datasource_mode_format", "data_source", ["ingestion_mode", "source_format"], unique=False)

    seed_connector_definitions()
    classify_existing_sources()


def downgrade() -> None:
    op.drop_index("idx_datasource_mode_format", table_name="data_source")
    op.drop_index("idx_datasource_connector_definition", table_name="data_source")
    op.drop_index(op.f("ix_data_source_normaliser_key"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_source_format"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_ingestion_mode"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_connector_definition_id"), table_name="data_source")
    op.drop_constraint("fk_data_source_connector_definition_id", "data_source", type_="foreignkey")
    op.drop_column("data_source", "normaliser_key")
    op.drop_column("data_source", "source_format")
    op.drop_column("data_source", "ingestion_mode")
    op.drop_column("data_source", "connector_definition_id")

    op.drop_index("idx_connector_definition_category_format", table_name="connector_definition")
    op.drop_index("idx_connector_definition_family_mode", table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_status"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_is_streaming_capable"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_normaliser_key"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_source_format"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_source_category"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_ingestion_mode"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_connector_family"), table_name="connector_definition")
    op.drop_index(op.f("ix_connector_definition_connector_key"), table_name="connector_definition")
    op.drop_table("connector_definition")


def seed_connector_definitions() -> None:
    bind = op.get_bind()
    definitions = [
        ("curriculum_pdf_upload", "Curriculum PDF Upload", "pdf_upload", "manual", "curriculum", "pdf", "curriculum_document_v1", False, False, "Upload, version, extract, chunk and index curriculum PDF files."),
        ("statssa_qlfs_pdf", "StatsSA QLFS PDF Connector", "pdf_download", "scheduled", "labour_market", "pdf", "statssa_qlfs_v1", False, False, "Download and parse StatsSA QLFS PDF publications."),
        ("esco_taxonomy_import", "ESCO Taxonomy Import", "taxonomy_import", "manual", "skills_taxonomy", "csv_json", "esco_taxonomy_v1", False, False, "Import ESCO skill taxonomy files from CSV or JSON."),
        ("generic_csv_upload", "Generic CSV Upload", "file_upload", "manual", "generic", "csv", "tabular_dataset_v1", False, False, "Upload tenant or shared CSV files for later contract-specific normalisation."),
        ("generic_excel_upload", "Generic Excel Upload", "file_upload", "manual", "generic", "xlsx", "tabular_dataset_v1", False, False, "Upload Excel workbooks for later contract-specific normalisation."),
        ("generic_api_pull", "Generic API Pull", "api_pull", "scheduled", "generic", "json_api", "api_payload_v1", False, True, "Pull JSON data from authenticated or public APIs."),
        ("job_board_api", "Job Board API Connector", "api_pull", "scheduled", "labour_market", "json_api", "job_advert_v1", False, True, "Pull job adverts from approved job-board APIs."),
        ("web_discovery", "Web Discovery Connector", "web_discovery", "scheduled", "generic", "html", "web_page_v1", False, False, "Discover and retrieve publicly indexed web pages for approved sources."),
        ("streaming_event", "Streaming Event Connector", "streaming", "streaming", "generic", "event_stream", "event_payload_v1", True, True, "Future connector for real-time or near-real-time event streams."),
        ("lms_connector", "LMS Connector", "api_pull", "scheduled", "institutional", "json_api", "lms_activity_v1", True, True, "Future learning-management-system source connector."),
        ("sis_connector", "SIS Connector", "api_pull", "scheduled", "institutional", "json_api", "student_information_v1", False, True, "Future student-information-system connector."),
        ("erp_connector", "ERP Connector", "api_pull", "scheduled", "institutional", "json_api", "erp_reference_v1", False, True, "Future institutional ERP connector."),
        ("professional_body_source", "Professional Body Source", "api_or_file", "scheduled", "reference", "mixed", "professional_requirement_v1", False, False, "Future professional body standards and skills source."),
        ("industry_association_source", "Industry Association Source", "api_or_file", "scheduled", "labour_market", "mixed", "industry_signal_v1", False, False, "Future industry association demand-signal source."),
    ]
    for item in definitions:
        bind.execute(
            sa.text(
                """
                INSERT INTO connector_definition (
                    connector_definition_id, connector_key, name, connector_family,
                    ingestion_mode, source_category, source_format, normaliser_key,
                    is_streaming_capable, requires_auth, description,
                    capability_profile, default_config, status
                )
                VALUES (
                    :connector_definition_id, :connector_key, :name, :connector_family,
                    :ingestion_mode, :source_category, :source_format, :normaliser_key,
                    :is_streaming_capable, :requires_auth, :description,
                    '{}'::jsonb, '{}'::jsonb, 'active'
                )
                ON CONFLICT (connector_key) DO NOTHING
                """
            ),
            {
                "connector_definition_id": str(uuid.uuid4()),
                "connector_key": item[0],
                "name": item[1],
                "connector_family": item[2],
                "ingestion_mode": item[3],
                "source_category": item[4],
                "source_format": item[5],
                "normaliser_key": item[6],
                "is_streaming_capable": item[7],
                "requires_auth": item[8],
                "description": item[9],
            },
        )


def classify_existing_sources() -> None:
    bind = op.get_bind()
    mappings = [
        ("curriculum_pdf", "curriculum_pdf_upload"),
        ("statssa_qlfs", "statssa_qlfs_pdf"),
        ("future_hook", "generic_api_pull"),
    ]
    for connector_type, connector_key in mappings:
        bind.execute(
            sa.text(
                """
                UPDATE data_source source
                SET connector_definition_id = definition.connector_definition_id,
                    connector_type = definition.connector_key,
                    ingestion_mode = definition.ingestion_mode,
                    source_format = definition.source_format,
                    normaliser_key = definition.normaliser_key
                FROM connector_definition definition
                WHERE source.connector_type = :connector_type
                  AND definition.connector_key = :connector_key
                """
            ),
            {"connector_type": connector_type, "connector_key": connector_key},
        )
