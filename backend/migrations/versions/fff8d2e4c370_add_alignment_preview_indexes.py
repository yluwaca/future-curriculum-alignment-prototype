"""add alignment preview indexes

Revision ID: fff8d2e4c370
Revises: fff7c1d3b260
Create Date: 2026-06-25 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "fff8d2e4c370"
down_revision: Union[str, Sequence[str], None] = "fff7c1d3b260"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_alignment_score_created_at",
        "alignment_score",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "idx_alignment_score_created_status",
        "alignment_score",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_alignment_score_created_status", table_name="alignment_score")
    op.drop_index("idx_alignment_score_created_at", table_name="alignment_score")
