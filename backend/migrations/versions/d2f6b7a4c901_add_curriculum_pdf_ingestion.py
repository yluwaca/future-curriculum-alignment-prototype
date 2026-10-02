"""add curriculum pdf ingestion

Revision ID: d2f6b7a4c901
Revises: c4a9d8e72b11
Create Date: 2026-06-16 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d2f6b7a4c901"
down_revision: Union[str, Sequence[str], None] = "c4a9d8e72b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "curriculum_document",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_key", sa.String(length=150), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("faculty", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=150), nullable=True),
        sa.Column("programme", sa.String(length=150), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("document_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("document_id"),
        sa.UniqueConstraint("document_key"),
    )
    op.create_index(op.f("ix_curriculum_document_document_key"), "curriculum_document", ["document_key"], unique=True)
    op.create_index(op.f("ix_curriculum_document_faculty"), "curriculum_document", ["faculty"], unique=False)
    op.create_index(op.f("ix_curriculum_document_department"), "curriculum_document", ["department"], unique=False)
    op.create_index(op.f("ix_curriculum_document_programme"), "curriculum_document", ["programme"], unique=False)
    op.create_index(op.f("ix_curriculum_document_status"), "curriculum_document", ["status"], unique=False)
    op.create_index(op.f("ix_curriculum_document_created_by"), "curriculum_document", ["created_by"], unique=False)
    op.create_index("idx_curriculum_document_programme_status", "curriculum_document", ["programme", "status"], unique=False)

    op.create_table(
        "curriculum_document_version",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_uri", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("extracted_text_hash", sa.String(length=64), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("extraction_status", sa.String(length=50), nullable=False),
        sa.Column("extraction_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("uploaded_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index(op.f("ix_curriculum_document_version_document_id"), "curriculum_document_version", ["document_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_job_id"), "curriculum_document_version", ["job_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_source_id"), "curriculum_document_version", ["source_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_raw_record_id"), "curriculum_document_version", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_content_hash"), "curriculum_document_version", ["content_hash"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_extracted_text_hash"), "curriculum_document_version", ["extracted_text_hash"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_extraction_status"), "curriculum_document_version", ["extraction_status"], unique=False)
    op.create_index(op.f("ix_curriculum_document_version_uploaded_by"), "curriculum_document_version", ["uploaded_by"], unique=False)
    op.create_index("idx_curriculum_document_version_number", "curriculum_document_version", ["document_id", "version_number"], unique=True)

    op.create_table(
        "document_chunk",
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(op.f("ix_document_chunk_version_id"), "document_chunk", ["version_id"], unique=False)
    op.create_index(op.f("ix_document_chunk_job_id"), "document_chunk", ["job_id"], unique=False)
    op.create_index(op.f("ix_document_chunk_raw_record_id"), "document_chunk", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_document_chunk_page_start"), "document_chunk", ["page_start"], unique=False)
    op.create_index(op.f("ix_document_chunk_content_hash"), "document_chunk", ["content_hash"], unique=False)
    op.create_index("idx_document_chunk_version_index", "document_chunk", ["version_id", "chunk_index"], unique=True)

    op.execute(
        """
        INSERT INTO data_source (
            source_id, source_key, name, source_type, source_category,
            connector_type, base_url, storage_path, refresh_policy, owner,
            status, is_authorised, config, auth_config
        )
        VALUES (
            '00000000-0000-4000-8000-000000000201', 'curriculum_pdf_upload',
            'Curriculum PDF Uploads', 'uploaded_pdf', 'curriculum',
            'curriculum_pdf', NULL, 'data/raw/curriculum', 'manual', 'system',
            'active', true, '{}'::jsonb, '{}'::jsonb
        )
        ON CONFLICT (source_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_document_chunk_version_index", table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_content_hash"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_page_start"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_raw_record_id"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_job_id"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_version_id"), table_name="document_chunk")
    op.drop_table("document_chunk")
    op.drop_index("idx_curriculum_document_version_number", table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_uploaded_by"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_extraction_status"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_extracted_text_hash"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_content_hash"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_raw_record_id"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_source_id"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_job_id"), table_name="curriculum_document_version")
    op.drop_index(op.f("ix_curriculum_document_version_document_id"), table_name="curriculum_document_version")
    op.drop_table("curriculum_document_version")
    op.drop_index("idx_curriculum_document_programme_status", table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_created_by"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_status"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_programme"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_department"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_faculty"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_document_key"), table_name="curriculum_document")
    op.drop_table("curriculum_document")
