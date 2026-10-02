"""add normaliser registry

Revision ID: ffc4e6f8b130
Revises: ffb3d5e7a920
Create Date: 2026-06-18 11:30:00.000000

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "ffc4e6f8b130"
down_revision: Union[str, Sequence[str], None] = "ffb3d5e7a920"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NORMALISERS = [
    {
        "normaliser_key": "curriculum_document_v1",
        "name": "Curriculum Document Normaliser",
        "source_category": "curriculum",
        "input_format": "pdf",
        "output_record_type": "curriculum_document",
        "supported_record_types": ["curriculum_pdf", "curriculum_extracted_text", "curriculum_document_chunk"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "preserve_raw_payload": True, "extract_sections": True},
        "schema": {"required": ["record_type", "source_record_id", "normalised_payload", "raw_payload"]},
        "description": "Normalises uploaded curriculum PDFs, extracted text, and document chunks.",
    },
    {
        "normaliser_key": "statssa_qlfs_v1",
        "name": "StatsSA QLFS Normaliser",
        "source_category": "labour_market",
        "input_format": "pdf",
        "output_record_type": "labour_market_table",
        "supported_record_types": ["statssa_qlfs_pdf", "statssa_qlfs_table"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "drop_empty_rows": True, "preserve_raw_payload": True, "clean_numeric_values": True},
        "schema": {"required": ["record_type", "normalised_payload", "raw_payload"]},
        "description": "Normalises StatsSA QLFS PDF metadata and extracted tables into cleaned labour-market records.",
    },
    {
        "normaliser_key": "esco_taxonomy_v1",
        "name": "ESCO Taxonomy Normaliser",
        "source_category": "skills_taxonomy",
        "input_format": "csv_json",
        "output_record_type": "esco_skill",
        "supported_record_types": ["esco_skill", "esco_taxonomy_record"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "dedupe_aliases": True},
        "schema": {"required": ["skill_uri", "preferred_label"]},
        "description": "Normalises ESCO skill taxonomy records.",
    },
    {
        "normaliser_key": "tabular_dataset_v1",
        "name": "Generic Tabular Dataset Normaliser",
        "source_category": "generic",
        "input_format": "csv_xlsx",
        "output_record_type": "tabular_record",
        "supported_record_types": ["csv_row", "xlsx_row", "generic_tabular_record"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "infer_numeric_values": True},
        "schema": {"required": ["raw_payload"]},
        "description": "Normalises generic CSV and Excel rows before source-specific contracts are added.",
    },
    {
        "normaliser_key": "api_payload_v1",
        "name": "Generic API Payload Normaliser",
        "source_category": "generic",
        "input_format": "json_api",
        "output_record_type": "api_payload",
        "supported_record_types": ["api_payload", "json_api_record"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "preserve_raw_payload": True},
        "schema": {"required": ["raw_payload"]},
        "description": "Normalises generic JSON API payloads.",
    },
    {
        "normaliser_key": "job_advert_v1",
        "name": "Job Advert Normaliser",
        "source_category": "labour_market",
        "input_format": "json_api",
        "output_record_type": "job_advert",
        "supported_record_types": ["job_advert", "job_posting"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "extract_skill_text": True},
        "schema": {"required": ["title", "description"]},
        "description": "Normalises approved job advert payloads for skill extraction.",
    },
    {
        "normaliser_key": "web_page_v1",
        "name": "Web Page Normaliser",
        "source_category": "generic",
        "input_format": "html",
        "output_record_type": "web_page",
        "supported_record_types": ["web_page", "html_document"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "strip_html": True},
        "schema": {"required": ["url", "text"]},
        "description": "Normalises approved discovered web pages.",
    },
    {
        "normaliser_key": "event_payload_v1",
        "name": "Streaming Event Normaliser",
        "source_category": "generic",
        "input_format": "event_stream",
        "output_record_type": "event_payload",
        "supported_record_types": ["event_payload"],
        "profile": {"trim_strings": True, "preserve_raw_payload": True},
        "schema": {"required": ["event_type", "event_time"]},
        "description": "Future normaliser for streaming event payloads.",
    },
    {
        "normaliser_key": "lms_activity_v1",
        "name": "LMS Activity Normaliser",
        "source_category": "institutional",
        "input_format": "json_api",
        "output_record_type": "lms_activity",
        "supported_record_types": ["lms_activity", "lms_course"],
        "profile": {"trim_strings": True, "collapse_whitespace": True},
        "schema": {"required": ["course_id"]},
        "description": "Future normaliser for LMS activity and course payloads.",
    },
    {
        "normaliser_key": "student_information_v1",
        "name": "Student Information Normaliser",
        "source_category": "institutional",
        "input_format": "json_api",
        "output_record_type": "student_information",
        "supported_record_types": ["student_information"],
        "profile": {"trim_strings": True, "deidentify_supported": True},
        "schema": {"required": ["student_key"]},
        "description": "Future normaliser for SIS payloads.",
    },
    {
        "normaliser_key": "erp_reference_v1",
        "name": "ERP Reference Normaliser",
        "source_category": "institutional",
        "input_format": "json_api",
        "output_record_type": "erp_reference",
        "supported_record_types": ["erp_reference"],
        "profile": {"trim_strings": True, "collapse_whitespace": True},
        "schema": {"required": ["reference_key"]},
        "description": "Future normaliser for ERP reference payloads.",
    },
    {
        "normaliser_key": "professional_requirement_v1",
        "name": "Professional Requirement Normaliser",
        "source_category": "reference",
        "input_format": "mixed",
        "output_record_type": "professional_requirement",
        "supported_record_types": ["professional_requirement"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "extract_skill_text": True},
        "schema": {"required": ["body", "source"]},
        "description": "Future normaliser for professional body standards.",
    },
    {
        "normaliser_key": "industry_signal_v1",
        "name": "Industry Signal Normaliser",
        "source_category": "labour_market",
        "input_format": "mixed",
        "output_record_type": "industry_signal",
        "supported_record_types": ["industry_signal"],
        "profile": {"trim_strings": True, "collapse_whitespace": True, "extract_skill_text": True},
        "schema": {"required": ["body", "source"]},
        "description": "Future normaliser for industry association demand signals.",
    },
]


def upgrade() -> None:
    op.create_table(
        "normaliser_definition",
        sa.Column("normaliser_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normaliser_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("source_category", sa.String(length=80), nullable=False),
        sa.Column("input_format", sa.String(length=80), nullable=False),
        sa.Column("output_record_type", sa.String(length=120), nullable=False),
        sa.Column("supported_record_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("transformation_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("normaliser_definition_id"),
        sa.UniqueConstraint("normaliser_key", "version", name="uq_normaliser_definition_key_version"),
    )
    op.create_index(op.f("ix_normaliser_definition_normaliser_key"), "normaliser_definition", ["normaliser_key"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_version"), "normaliser_definition", ["version"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_source_category"), "normaliser_definition", ["source_category"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_input_format"), "normaliser_definition", ["input_format"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_output_record_type"), "normaliser_definition", ["output_record_type"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_is_default"), "normaliser_definition", ["is_default"], unique=False)
    op.create_index(op.f("ix_normaliser_definition_status"), "normaliser_definition", ["status"], unique=False)
    op.create_index("idx_normaliser_key_status", "normaliser_definition", ["normaliser_key", "status"], unique=False)
    op.create_index("idx_normaliser_category_format", "normaliser_definition", ["source_category", "input_format"], unique=False)

    op.add_column("cleaned_ingestion_record", sa.Column("normaliser_definition_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("cleaned_ingestion_record", sa.Column("normaliser_key", sa.String(length=150), nullable=True))
    op.add_column("cleaned_ingestion_record", sa.Column("normaliser_version", sa.String(length=50), nullable=True))
    op.create_foreign_key(
        "fk_cleaned_ingestion_record_normaliser_definition_id",
        "cleaned_ingestion_record",
        "normaliser_definition",
        ["normaliser_definition_id"],
        ["normaliser_definition_id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_cleaned_ingestion_record_normaliser_definition_id"), "cleaned_ingestion_record", ["normaliser_definition_id"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_normaliser_key"), "cleaned_ingestion_record", ["normaliser_key"], unique=False)
    op.create_index(op.f("ix_cleaned_ingestion_record_normaliser_version"), "cleaned_ingestion_record", ["normaliser_version"], unique=False)

    seed_normalisers()
    backfill_cleaned_normalisers()


def downgrade() -> None:
    op.drop_index(op.f("ix_cleaned_ingestion_record_normaliser_version"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_normaliser_key"), table_name="cleaned_ingestion_record")
    op.drop_index(op.f("ix_cleaned_ingestion_record_normaliser_definition_id"), table_name="cleaned_ingestion_record")
    op.drop_constraint("fk_cleaned_ingestion_record_normaliser_definition_id", "cleaned_ingestion_record", type_="foreignkey")
    op.drop_column("cleaned_ingestion_record", "normaliser_version")
    op.drop_column("cleaned_ingestion_record", "normaliser_key")
    op.drop_column("cleaned_ingestion_record", "normaliser_definition_id")

    op.drop_index("idx_normaliser_category_format", table_name="normaliser_definition")
    op.drop_index("idx_normaliser_key_status", table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_status"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_is_default"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_output_record_type"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_input_format"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_source_category"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_version"), table_name="normaliser_definition")
    op.drop_index(op.f("ix_normaliser_definition_normaliser_key"), table_name="normaliser_definition")
    op.drop_table("normaliser_definition")


def seed_normalisers() -> None:
    bind = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO normaliser_definition (
            normaliser_definition_id, normaliser_key, name, version, source_category,
            input_format, output_record_type, supported_record_types,
            transformation_profile, output_schema, is_default, status, description
        )
        VALUES (
            :normaliser_definition_id, :normaliser_key, :name, '1.0.0',
            :source_category, :input_format, :output_record_type,
            CAST(:supported_record_types AS jsonb), CAST(:transformation_profile AS jsonb),
            CAST(:output_schema AS jsonb), true, 'active', :description
        )
        ON CONFLICT (normaliser_key, version) DO NOTHING
        """
    )
    for item in NORMALISERS:
        bind.execute(
            statement,
            {
                "normaliser_definition_id": str(uuid.uuid4()),
                "normaliser_key": item["normaliser_key"],
                "name": item["name"],
                "source_category": item["source_category"],
                "input_format": item["input_format"],
                "output_record_type": item["output_record_type"],
                "supported_record_types": json.dumps(item["supported_record_types"]),
                "transformation_profile": json.dumps(item["profile"]),
                "output_schema": json.dumps(item["schema"]),
                "description": item["description"],
            },
        )


def backfill_cleaned_normalisers() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE cleaned_ingestion_record cleaned
            SET normaliser_definition_id = normaliser.normaliser_definition_id,
                normaliser_key = normaliser.normaliser_key,
                normaliser_version = normaliser.version,
                cleaning_metadata = COALESCE(cleaning_metadata, '{}'::jsonb) ||
                    jsonb_build_object(
                        'normaliser_key', normaliser.normaliser_key,
                        'normaliser_version', normaliser.version
                    )
            FROM raw_ingestion_record raw
            JOIN data_source source ON raw.source_id = source.source_id
            JOIN normaliser_definition normaliser ON source.normaliser_key = normaliser.normaliser_key
            WHERE cleaned.raw_record_id = raw.record_id
              AND cleaned.normaliser_definition_id IS NULL
              AND normaliser.status = 'active'
            """
        )
    )
