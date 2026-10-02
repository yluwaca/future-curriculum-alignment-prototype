"""add lime_summary to predictive_output

Revision ID: b4c5d6e7f801
Revises: a1b2c3d4e5f6
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b4c5d6e7f801"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "predictive_output",
        sa.Column(
            "lime_summary",
            JSONB,
            nullable=True,
            comment="LIME instance-level explanation",
        ),
    )


def downgrade() -> None:
    op.drop_column("predictive_output", "lime_summary")
