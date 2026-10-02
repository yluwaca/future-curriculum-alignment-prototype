"""Add user approval fields

Revision ID: a1b2c3d4e5f6
Revises: fff8d2e4c370
Create Date: 2026-07-15

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "a1b2c3d4e5f6"
down_revision = "3c4d5e6f7a03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "approval_status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "approved_by",
            sa.String(100),
            nullable=True,
        ),
    )
    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "rejection_reason",
            sa.String(500),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_identity_approval_status",
        "jus01_systemidentity",
        ["approval_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_identity_approval_status",
        table_name="jus01_systemidentity",
    )
    op.drop_column(
        "jus01_systemidentity",
        "rejection_reason",
    )
    op.drop_column(
        "jus01_systemidentity",
        "approved_at",
    )
    op.drop_column(
        "jus01_systemidentity",
        "approved_by",
    )
    op.drop_column(
        "jus01_systemidentity",
        "approval_status",
    )
