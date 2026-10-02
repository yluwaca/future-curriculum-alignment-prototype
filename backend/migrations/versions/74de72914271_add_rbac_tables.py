"""add rbac tables

Revision ID: 74de72914271
Revises: f8babc1394c7
Create Date: 2026-03-08 20:20:29.099747
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74de72914271'
down_revision: Union[str, Sequence[str], None] = 'f8babc1394c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # =========================
    # Role Table
    # =========================
    op.create_table(
        "sec02_role",
        sa.Column("role_id", sa.String(50), primary_key=True),
        sa.Column("role_name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255))
    )

    # =========================
    # Permission Table
    # =========================
    op.create_table(
        "sec03_permission",
        sa.Column("permission_id", sa.String(100), primary_key=True),
        sa.Column("description", sa.String(255))
    )

    # =========================
    # User → Role
    # =========================
    op.create_table(
        "sec05_userrole",
        sa.Column(
            "identity_id",
            sa.String,
            sa.ForeignKey("jus01_systemidentity.identity_id"),
            primary_key=True
        ),
        sa.Column(
            "role_id",
            sa.String,
            sa.ForeignKey("sec02_role.role_id"),
            primary_key=True
        )
    )

    # =========================
    # Role → Permission
    # =========================
    op.create_table(
        "sec04_rolepermission",
        sa.Column(
            "role_id",
            sa.String,
            sa.ForeignKey("sec02_role.role_id"),
            primary_key=True
        ),
        sa.Column(
            "permission_id",
            sa.String,
            sa.ForeignKey("sec03_permission.permission_id"),
            primary_key=True
        )
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_table("sec04_rolepermission")
    op.drop_table("sec05_userrole")
    op.drop_table("sec03_permission")
    op.drop_table("sec02_role")