"""add labour market trends

Revision ID: e1f2a3b4c506
Revises: d0e7f8a9b104
Create Date: 2026-06-17 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1f2a3b4c506"
down_revision: Union[str, Sequence[str], None] = "d0e7f8a9b104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "labour_market_trend",
        sa.Column("trend_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cleaned_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("indicator_name", sa.String(length=500), nullable=False),
        sa.Column("measure_name", sa.String(length=255), nullable=False),
        sa.Column("dimension_type", sa.String(length=100), nullable=False),
        sa.Column("dimension_value", sa.String(length=255), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("table_title", sa.Text(), nullable=True),
        sa.Column("observation_hash", sa.String(length=64), nullable=False),
        sa.Column("extraction_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["cleaned_record_id"], ["cleaned_ingestion_record.cleaned_record_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["ingestion_job.job_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_ingestion_record.record_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["data_source.source_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("trend_id"),
        sa.UniqueConstraint("observation_hash", name="uq_labour_market_trend_hash"),
    )
    op.create_index(op.f("ix_labour_market_trend_cleaned_record_id"), "labour_market_trend", ["cleaned_record_id"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_raw_record_id"), "labour_market_trend", ["raw_record_id"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_job_id"), "labour_market_trend", ["job_id"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_source_id"), "labour_market_trend", ["source_id"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_indicator_name"), "labour_market_trend", ["indicator_name"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_measure_name"), "labour_market_trend", ["measure_name"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_dimension_type"), "labour_market_trend", ["dimension_type"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_dimension_value"), "labour_market_trend", ["dimension_value"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_year"), "labour_market_trend", ["year"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_quarter"), "labour_market_trend", ["quarter"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_source_file"), "labour_market_trend", ["source_file"], unique=False)
    op.create_index(op.f("ix_labour_market_trend_observation_hash"), "labour_market_trend", ["observation_hash"], unique=False)
    op.create_index("idx_labour_market_trend_skill_time", "labour_market_trend", ["indicator_name", "year", "quarter"], unique=False)
    op.create_index("idx_labour_market_trend_dimension", "labour_market_trend", ["dimension_type", "dimension_value"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_labour_market_trend_dimension", table_name="labour_market_trend")
    op.drop_index("idx_labour_market_trend_skill_time", table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_observation_hash"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_source_file"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_quarter"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_year"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_dimension_value"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_dimension_type"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_measure_name"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_indicator_name"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_source_id"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_job_id"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_raw_record_id"), table_name="labour_market_trend")
    op.drop_index(op.f("ix_labour_market_trend_cleaned_record_id"), table_name="labour_market_trend")
    op.drop_table("labour_market_trend")
