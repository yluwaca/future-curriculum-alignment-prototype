"""
Add SA OFO (Organising Framework for Occupations) taxonomy tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "2b3c4d5e6f02"
down_revision = "06555b877986"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ofo_skill",
        sa.Column("ofo_skill_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("skill_id", UUID(as_uuid=True), sa.ForeignKey("skill.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("ofo_code", sa.String(20), nullable=True),
        sa.Column("preferred_label", sa.String(255), nullable=False),
        sa.Column("skill_type", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("taxonomy_version", sa.String(50), nullable=False, server_default="starter"),
        sa.Column("ofo_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("ofo_skill.ofo_skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("top_concept", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ofo_skill_label_type", "ofo_skill", ["preferred_label", "skill_type"])
    op.create_index("idx_ofo_skill_parent_id", "ofo_skill", ["parent_id"])
    op.create_index("idx_ofo_skill_code", "ofo_skill", ["ofo_code"])

    op.create_table(
        "ofo_occupation",
        sa.Column("ofo_occupation_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ofo_code", sa.String(20), nullable=False),
        sa.Column("preferred_label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("taxonomy_version", sa.String(50), nullable=False, server_default="starter"),
        sa.Column("occupation_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("parent_id", UUID(as_uuid=True), sa.ForeignKey("ofo_occupation.ofo_occupation_id", ondelete="SET NULL"), nullable=True),
        sa.Column("broader_occupation_code", sa.String(20), nullable=True),
        sa.Column("top_concept", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ofo_occupation_code", "ofo_occupation", ["ofo_code"])
    op.create_index("idx_ofo_occupation_parent_id", "ofo_occupation", ["parent_id"])

    op.create_table(
        "ofo_occupation_skill_link",
        sa.Column("link_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("occupation_id", UUID(as_uuid=True), sa.ForeignKey("ofo_occupation.ofo_occupation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", UUID(as_uuid=True), sa.ForeignKey("ofo_skill.ofo_skill_id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(20), nullable=False, server_default="essential"),
        sa.Column("skill_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("occupation_id", "skill_id", name="uq_ofo_occ_skill"),
    )
    op.create_index("idx_ofo_occ_skill_link_occ", "ofo_occupation_skill_link", ["occupation_id"])
    op.create_index("idx_ofo_occ_skill_link_skill", "ofo_occupation_skill_link", ["skill_id"])


def downgrade():
    op.drop_table("ofo_occupation_skill_link")
    op.drop_table("ofo_occupation")
    op.drop_table("ofo_skill")
