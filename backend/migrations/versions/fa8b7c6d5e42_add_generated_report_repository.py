"""add generated report repository

Revision ID: fa8b7c6d5e42
Revises: f7c9d2e4a615
Create Date: 2026-06-17 08:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fa8b7c6d5e42"
down_revision: Union[str, Sequence[str], None] = "f7c9d2e4a615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generated_report",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_type", sa.String(length=120), nullable=False),
        sa.Column("source_entity_type", sa.String(length=120), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_by", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("format_hint", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index(op.f("ix_generated_report_report_type"), "generated_report", ["report_type"], unique=False)
    op.create_index(op.f("ix_generated_report_source_entity_type"), "generated_report", ["source_entity_type"], unique=False)
    op.create_index(op.f("ix_generated_report_source_entity_id"), "generated_report", ["source_entity_id"], unique=False)
    op.create_index(op.f("ix_generated_report_generated_by"), "generated_report", ["generated_by"], unique=False)
    op.create_index(op.f("ix_generated_report_status"), "generated_report", ["status"], unique=False)
    op.create_index(op.f("ix_generated_report_payload_hash"), "generated_report", ["payload_hash"], unique=False)
    op.create_index("idx_generated_report_type_created", "generated_report", ["report_type", "created_at"], unique=False)
    op.create_index("idx_generated_report_source", "generated_report", ["source_entity_type", "source_entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_generated_report_source", table_name="generated_report")
    op.drop_index("idx_generated_report_type_created", table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_payload_hash"), table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_status"), table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_generated_by"), table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_source_entity_id"), table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_source_entity_type"), table_name="generated_report")
    op.drop_index(op.f("ix_generated_report_report_type"), table_name="generated_report")
    op.drop_table("generated_report")
