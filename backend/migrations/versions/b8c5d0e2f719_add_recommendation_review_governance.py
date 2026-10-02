"""add recommendation review governance

Revision ID: b8c5d0e2f719
Revises: a7b4c9d1e608
Create Date: 2026-06-16 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8c5d0e2f719"
down_revision: Union[str, Sequence[str], None] = "a7b4c9d1e608"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_review",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("previous_status", sa.String(length=50), nullable=False),
        sa.Column("new_status", sa.String(length=50), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("modified_title", sa.String(length=255), nullable=True),
        sa.Column("modified_description", sa.Text(), nullable=True),
        sa.Column("modified_priority", sa.String(length=50), nullable=True),
        sa.Column("review_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.recommendation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index(op.f("ix_recommendation_review_recommendation_id"), "recommendation_review", ["recommendation_id"], unique=False)
    op.create_index(op.f("ix_recommendation_review_reviewer_id"), "recommendation_review", ["reviewer_id"], unique=False)
    op.create_index(op.f("ix_recommendation_review_decision"), "recommendation_review", ["decision"], unique=False)
    op.create_index(op.f("ix_recommendation_review_new_status"), "recommendation_review", ["new_status"], unique=False)
    op.create_index("idx_recommendation_review_decision", "recommendation_review", ["recommendation_id", "decision"], unique=False)
    op.create_index("idx_recommendation_review_reviewer", "recommendation_review", ["reviewer_id", "created_at"], unique=False)

    op.create_table(
        "recommendation_feedback",
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("feedback_type", sa.String(length=100), nullable=False),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("feedback_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.recommendation_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_id"], ["recommendation_review.review_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("feedback_id"),
    )
    op.create_index(op.f("ix_recommendation_feedback_recommendation_id"), "recommendation_feedback", ["recommendation_id"], unique=False)
    op.create_index(op.f("ix_recommendation_feedback_review_id"), "recommendation_feedback", ["review_id"], unique=False)
    op.create_index(op.f("ix_recommendation_feedback_reviewer_id"), "recommendation_feedback", ["reviewer_id"], unique=False)
    op.create_index(op.f("ix_recommendation_feedback_feedback_type"), "recommendation_feedback", ["feedback_type"], unique=False)
    op.create_index("idx_recommendation_feedback_type", "recommendation_feedback", ["recommendation_id", "feedback_type"], unique=False)

    op.create_table(
        "recommendation_status_history",
        sa.Column("history_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_by", sa.String(length=100), nullable=True),
        sa.Column("previous_status", sa.String(length=50), nullable=True),
        sa.Column("new_status", sa.String(length=50), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("transition_type", sa.String(length=100), nullable=False),
        sa.Column("history_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.recommendation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("history_id"),
    )
    op.create_index(op.f("ix_recommendation_status_history_recommendation_id"), "recommendation_status_history", ["recommendation_id"], unique=False)
    op.create_index(op.f("ix_recommendation_status_history_changed_by"), "recommendation_status_history", ["changed_by"], unique=False)
    op.create_index(op.f("ix_recommendation_status_history_previous_status"), "recommendation_status_history", ["previous_status"], unique=False)
    op.create_index(op.f("ix_recommendation_status_history_new_status"), "recommendation_status_history", ["new_status"], unique=False)
    op.create_index(op.f("ix_recommendation_status_history_transition_type"), "recommendation_status_history", ["transition_type"], unique=False)
    op.create_index("idx_recommendation_status_history_transition", "recommendation_status_history", ["recommendation_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_recommendation_status_history_transition", table_name="recommendation_status_history")
    op.drop_index(op.f("ix_recommendation_status_history_transition_type"), table_name="recommendation_status_history")
    op.drop_index(op.f("ix_recommendation_status_history_new_status"), table_name="recommendation_status_history")
    op.drop_index(op.f("ix_recommendation_status_history_previous_status"), table_name="recommendation_status_history")
    op.drop_index(op.f("ix_recommendation_status_history_changed_by"), table_name="recommendation_status_history")
    op.drop_index(op.f("ix_recommendation_status_history_recommendation_id"), table_name="recommendation_status_history")
    op.drop_table("recommendation_status_history")
    op.drop_index("idx_recommendation_feedback_type", table_name="recommendation_feedback")
    op.drop_index(op.f("ix_recommendation_feedback_feedback_type"), table_name="recommendation_feedback")
    op.drop_index(op.f("ix_recommendation_feedback_reviewer_id"), table_name="recommendation_feedback")
    op.drop_index(op.f("ix_recommendation_feedback_review_id"), table_name="recommendation_feedback")
    op.drop_index(op.f("ix_recommendation_feedback_recommendation_id"), table_name="recommendation_feedback")
    op.drop_table("recommendation_feedback")
    op.drop_index("idx_recommendation_review_reviewer", table_name="recommendation_review")
    op.drop_index("idx_recommendation_review_decision", table_name="recommendation_review")
    op.drop_index(op.f("ix_recommendation_review_new_status"), table_name="recommendation_review")
    op.drop_index(op.f("ix_recommendation_review_decision"), table_name="recommendation_review")
    op.drop_index(op.f("ix_recommendation_review_reviewer_id"), table_name="recommendation_review")
    op.drop_index(op.f("ix_recommendation_review_recommendation_id"), table_name="recommendation_review")
    op.drop_table("recommendation_review")
