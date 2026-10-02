"""add traceability fields to predictive_output

Revision ID: c5d6e7f80912
Revises: b4c5d6e7f801
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa

revision = "c5d6e7f80912"
down_revision = "b4c5d6e7f801"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "predictive_output",
        sa.Column(
            "triggered_by",
            sa.String(100),
            nullable=True,
            comment="User_ID who triggered the prediction",
        ),
    )
    op.add_column(
        "predictive_output",
        sa.Column(
            "action_taken",
            sa.String(50),
            nullable=True,
            comment="Action: predicted, approved, rejected, deferred",
        ),
    )
    op.add_column(
        "predictive_output",
        sa.Column(
            "user_justification",
            sa.String(1000),
            nullable=True,
            comment="User justification for action taken",
        ),
    )


def downgrade() -> None:
    op.drop_column("predictive_output", "triggered_by")
    op.drop_column("predictive_output", "action_taken")
    op.drop_column("predictive_output", "user_justification")
