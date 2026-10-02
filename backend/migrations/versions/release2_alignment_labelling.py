"""add independent alignment labelling workflow

Revision ID: release2_alignment_labels
Revises: release2_skill_review
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release2_alignment_labels"
down_revision = "release2_skill_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alignment_review_task",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_window_hash", sa.String(length=64), nullable=False),
        sa.Column("curriculum_evidence", sa.Text(), nullable=False),
        sa.Column("labour_market_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("final_alignment_label", sa.Integer(), nullable=True),
        sa.Column("finalised_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('awaiting_first_review','awaiting_second_review','adjudication_required','completed')", name="ck_alignment_review_task_status"),
        sa.CheckConstraint("final_alignment_label IS NULL OR (final_alignment_label >= 1 AND final_alignment_label <= 5)", name="ck_alignment_review_task_final_label"),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunk.chunk_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalised_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("task_id"),
        sa.UniqueConstraint("version_id", "chunk_id", "evidence_window_hash", name="uq_alignment_review_task_evidence"),
    )
    for column in ("document_id", "version_id", "chunk_id", "status"):
        op.create_index(f"ix_alignment_review_task_{column}", "alignment_review_task", [column])
    op.create_index("idx_alignment_review_task_status_created", "alignment_review_task", ["status", "created_at"])

    op.create_table(
        "alignment_expert_label",
        sa.Column("label_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_stage", sa.String(length=30), nullable=False),
        sa.Column("alignment_label", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("present_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewer_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("review_stage IN ('first','second','adjudication')", name="ck_alignment_expert_label_stage"),
        sa.CheckConstraint("alignment_label >= 1 AND alignment_label <= 5", name="ck_alignment_expert_label_value"),
        sa.CheckConstraint("confidence >= 1 AND confidence <= 5", name="ck_alignment_expert_label_confidence"),
        sa.ForeignKeyConstraint(["task_id"], ["alignment_review_task.task_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["jus01_systemidentity.identity_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("label_id"),
        sa.UniqueConstraint("task_id", "review_stage", name="uq_alignment_expert_label_task_stage"),
    )
    for column in ("task_id", "review_stage", "reviewer_id"):
        op.create_index(f"ix_alignment_expert_label_{column}", "alignment_expert_label", [column])
    op.create_index("idx_alignment_expert_label_task_created", "alignment_expert_label", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_table("alignment_expert_label")
    op.drop_table("alignment_review_task")
