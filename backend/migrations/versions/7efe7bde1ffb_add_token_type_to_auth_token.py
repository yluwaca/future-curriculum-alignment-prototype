"""add token_type to auth_token

Revision ID: 7efe7bde1ffb
Revises: 95f9e35670d5
Create Date: 2026-03-08 22:44:22.628232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7efe7bde1ffb'
down_revision: Union[str, Sequence[str], None] = '95f9e35670d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "sec01_authtoken",
        sa.Column("token_type", sa.String(length=20), nullable=False, server_default="refresh")
    )


def downgrade():
    op.drop_column("sec01_authtoken", "token_type")