"""add skill governance fields

Revision ID: fd2e4f6a8b10
Revises: fc1d2e3f4a65
Create Date: 2026-06-17 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fd2e4f6a8b10"
down_revision: Union[str, Sequence[str], None] = "fc1d2e3f4a65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("skill_mapping", sa.Column("reviewed_by", sa.String(length=100), nullable=True))
    op.add_column("skill_mapping", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("skill_mapping", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "skill_mapping",
        sa.Column("confidence_calibration", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_foreign_key(
        "fk_skill_mapping_reviewed_by",
        "skill_mapping",
        "jus01_systemidentity",
        ["reviewed_by"],
        ["identity_id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_skill_mapping_reviewed_by"), "skill_mapping", ["reviewed_by"], unique=False)
    op.alter_column("skill_mapping", "confidence_calibration", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_skill_mapping_reviewed_by"), table_name="skill_mapping")
    op.drop_constraint("fk_skill_mapping_reviewed_by", "skill_mapping", type_="foreignkey")
    op.drop_column("skill_mapping", "confidence_calibration")
    op.drop_column("skill_mapping", "review_note")
    op.drop_column("skill_mapping", "reviewed_at")
    op.drop_column("skill_mapping", "reviewed_by")
