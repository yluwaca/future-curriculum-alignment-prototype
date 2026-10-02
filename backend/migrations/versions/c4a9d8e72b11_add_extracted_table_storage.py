"""add extracted table storage

Revision ID: c4a9d8e72b11
Revises: b7f3d2a91c10
Create Date: 2026-06-16 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4a9d8e72b11"
down_revision: Union[str, Sequence[str], None] = "b7f3d2a91c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extracted_table",
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=False),
        sa.Column("document_uri", sa.String(length=1000), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("table_index", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("quarter", sa.String(length=10), nullable=True),
        sa.Column("series_code", sa.String(length=50), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("extraction_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("table_id"),
    )
    op.create_index(op.f("ix_extracted_table_job_id"), "extracted_table", ["job_id"], unique=False)
    op.create_index(op.f("ix_extracted_table_source_id"), "extracted_table", ["source_id"], unique=False)
    op.create_index(op.f("ix_extracted_table_raw_record_id"), "extracted_table", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_extracted_table_source_file"), "extracted_table", ["source_file"], unique=False)
    op.create_index(op.f("ix_extracted_table_page_number"), "extracted_table", ["page_number"], unique=False)
    op.create_index(op.f("ix_extracted_table_year"), "extracted_table", ["year"], unique=False)
    op.create_index(op.f("ix_extracted_table_quarter"), "extracted_table", ["quarter"], unique=False)
    op.create_index(op.f("ix_extracted_table_series_code"), "extracted_table", ["series_code"], unique=False)
    op.create_index("idx_extracted_table_job_source_file", "extracted_table", ["job_id", "source_file"], unique=False)
    op.create_index("idx_extracted_table_document_position", "extracted_table", ["source_file", "page_number", "table_index"], unique=False)

    op.create_table(
        "extracted_table_row",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalised_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["table_id"], ["extracted_table.table_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("row_id"),
    )
    op.create_index(op.f("ix_extracted_table_row_table_id"), "extracted_table_row", ["table_id"], unique=False)
    op.create_index(op.f("ix_extracted_table_row_content_hash"), "extracted_table_row", ["content_hash"], unique=False)
    op.create_index("idx_extracted_table_row_table_number", "extracted_table_row", ["table_id", "row_number"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_extracted_table_row_table_number", table_name="extracted_table_row")
    op.drop_index(op.f("ix_extracted_table_row_content_hash"), table_name="extracted_table_row")
    op.drop_index(op.f("ix_extracted_table_row_table_id"), table_name="extracted_table_row")
    op.drop_table("extracted_table_row")
    op.drop_index("idx_extracted_table_document_position", table_name="extracted_table")
    op.drop_index("idx_extracted_table_job_source_file", table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_series_code"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_quarter"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_year"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_page_number"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_source_file"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_raw_record_id"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_source_id"), table_name="extracted_table")
    op.drop_index(op.f("ix_extracted_table_job_id"), table_name="extracted_table")
    op.drop_table("extracted_table")
