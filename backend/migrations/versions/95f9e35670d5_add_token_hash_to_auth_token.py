"""add token_hash to auth_token

Revision ID: 95f9e35670d5
Revises: 6bd96643a6c5
Create Date: 2026-03-08 22:17:27.658817

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95f9e35670d5'
down_revision: Union[str, Sequence[str], None] = '6bd96643a6c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
       # 1️⃣ Add column as nullable
    op.add_column(
        "sec01_authtoken",
        sa.Column("token_hash", sa.String(length=64), nullable=True)
    )

    # 2️⃣ Populate existing rows
    op.execute(
        """
        UPDATE sec01_authtoken
        SET token_hash = md5(token_id::text)
        """
    )

    # 3️⃣ Enforce NOT NULL
    op.alter_column(
        "sec01_authtoken",
        "token_hash",
        nullable=False
    )

    # 4️⃣ Create index
    op.create_index(
        "ix_sec01_authtoken_token_hash",
        "sec01_authtoken",
        ["token_hash"],
        unique=True
    )


def downgrade():
    op.drop_index("ix_sec01_authtoken_token_hash", table_name="sec01_authtoken")
    op.drop_column("sec01_authtoken", "token_hash")