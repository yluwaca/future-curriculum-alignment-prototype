"""add_esco_hierarchy_parent_id_top_concept

Revision ID: a8f64e3ecf7d
Revises: fff8d2e4c370
Create Date: 2026-07-06 19:45:30.071041

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8f64e3ecf7d"
down_revision: Union[str, Sequence[str], None] = "fff8d2e4c370"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("esco_skill", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("esco_skill", sa.Column("broader_concept_uri", sa.String(length=1000), nullable=True))
    op.add_column("esco_skill", sa.Column("top_concept", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_foreign_key(
        "fk_esco_skill_parent_id",
        "esco_skill", "esco_skill",
        ["parent_id"], ["esco_skill_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_esco_skill_parent_id", "esco_skill", ["parent_id"], unique=False)
    op.create_index("idx_esco_skill_top_concept", "esco_skill", ["top_concept"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_esco_skill_top_concept", table_name="esco_skill")
    op.drop_index("idx_esco_skill_parent_id", table_name="esco_skill")
    op.drop_constraint("fk_esco_skill_parent_id", "esco_skill", type_="foreignkey")
    op.drop_column("esco_skill", "top_concept")
    op.drop_column("esco_skill", "broader_concept_uri")
    op.drop_column("esco_skill", "parent_id")
