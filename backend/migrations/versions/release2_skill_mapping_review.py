"""add immutable skill mapping review history

Revision ID: release2_skill_review
Revises: release2_curriculum_review
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release2_skill_review"
down_revision = "release2_curriculum_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_mapping_review_event",
        sa.Column("review_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_status", sa.String(length=50), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("previous_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["mapping_id"], ["skill_mapping.mapping_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("review_event_id"),
    )
    op.create_index("ix_skill_mapping_review_event_mapping_id", "skill_mapping_review_event", ["mapping_id"])
    op.create_index("ix_skill_mapping_review_event_decision", "skill_mapping_review_event", ["decision"])
    op.create_index("ix_skill_mapping_review_event_reviewer_id", "skill_mapping_review_event", ["reviewer_id"])
    op.create_index(
        "idx_skill_mapping_review_event_mapping_created",
        "skill_mapping_review_event",
        ["mapping_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("skill_mapping_review_event")
