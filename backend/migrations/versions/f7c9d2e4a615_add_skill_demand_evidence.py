"""add skill demand evidence

Revision ID: f7c9d2e4a615
Revises: f2a4b6c8d010
Create Date: 2026-06-17 07:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f7c9d2e4a615"
down_revision: Union[str, Sequence[str], None] = "f2a4b6c8d010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_demand_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(length=100), nullable=False),
        sa.Column("match_method", sa.String(length=100), nullable=False),
        sa.Column("matched_context", sa.String(length=255), nullable=False),
        sa.Column("demand_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_weight", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["labour_market_signal.signal_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
        sa.UniqueConstraint("evidence_hash", name="uq_skill_demand_evidence_hash"),
    )
    op.create_index(op.f("ix_skill_demand_evidence_skill_id"), "skill_demand_evidence", ["skill_id"], unique=False)
    op.create_index(op.f("ix_skill_demand_evidence_signal_id"), "skill_demand_evidence", ["signal_id"], unique=False)
    op.create_index(op.f("ix_skill_demand_evidence_evidence_type"), "skill_demand_evidence", ["evidence_type"], unique=False)
    op.create_index(op.f("ix_skill_demand_evidence_evidence_hash"), "skill_demand_evidence", ["evidence_hash"], unique=False)
    op.create_index(
        "idx_skill_demand_evidence_skill_score",
        "skill_demand_evidence",
        ["skill_id", "demand_score", "confidence_score"],
        unique=False,
    )
    op.create_index(
        "idx_skill_demand_evidence_signal_skill",
        "skill_demand_evidence",
        ["signal_id", "skill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_skill_demand_evidence_signal_skill", table_name="skill_demand_evidence")
    op.drop_index("idx_skill_demand_evidence_skill_score", table_name="skill_demand_evidence")
    op.drop_index(op.f("ix_skill_demand_evidence_evidence_hash"), table_name="skill_demand_evidence")
    op.drop_index(op.f("ix_skill_demand_evidence_evidence_type"), table_name="skill_demand_evidence")
    op.drop_index(op.f("ix_skill_demand_evidence_signal_id"), table_name="skill_demand_evidence")
    op.drop_index(op.f("ix_skill_demand_evidence_skill_id"), table_name="skill_demand_evidence")
    op.drop_table("skill_demand_evidence")
