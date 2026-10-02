"""add labour market signals

Revision ID: f2a4b6c8d010
Revises: e1f2a3b4c506
Create Date: 2026-06-17 03:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2a4b6c8d010"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "labour_market_signal",
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_key", sa.String(length=120), nullable=False),
        sa.Column("canonical_name", sa.String(length=255), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("dimension_type", sa.String(length=100), nullable=False),
        sa.Column("dimension_value", sa.String(length=255), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.String(length=10), nullable=False),
        sa.Column("observed_value", sa.Float(), nullable=False),
        sa.Column("normalised_value", sa.Float(), nullable=False),
        sa.Column("demand_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("source_summary", sa.Text(), nullable=True),
        sa.Column("signal_hash", sa.String(length=64), nullable=False),
        sa.Column("signal_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("signal_id"),
        sa.UniqueConstraint("signal_hash", name="uq_labour_market_signal_hash"),
    )
    op.create_index(op.f("ix_labour_market_signal_canonical_key"), "labour_market_signal", ["canonical_key"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_signal_type"), "labour_market_signal", ["signal_type"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_dimension_type"), "labour_market_signal", ["dimension_type"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_dimension_value"), "labour_market_signal", ["dimension_value"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_year"), "labour_market_signal", ["year"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_quarter"), "labour_market_signal", ["quarter"], unique=False)
    op.create_index(op.f("ix_labour_market_signal_signal_hash"), "labour_market_signal", ["signal_hash"], unique=False)
    op.create_index("idx_labour_market_signal_period", "labour_market_signal", ["year", "quarter"], unique=False)
    op.create_index(
        "idx_labour_market_signal_canonical_dimension",
        "labour_market_signal",
        ["canonical_key", "dimension_type", "dimension_value"],
        unique=False,
    )
    op.create_index(
        "idx_labour_market_signal_score",
        "labour_market_signal",
        ["demand_score", "confidence_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_labour_market_signal_score", table_name="labour_market_signal")
    op.drop_index("idx_labour_market_signal_canonical_dimension", table_name="labour_market_signal")
    op.drop_index("idx_labour_market_signal_period", table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_signal_hash"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_quarter"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_year"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_dimension_value"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_dimension_type"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_signal_type"), table_name="labour_market_signal")
    op.drop_index(op.f("ix_labour_market_signal_canonical_key"), table_name="labour_market_signal")
    op.drop_table("labour_market_signal")
