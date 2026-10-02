"""add curriculum evidence expert review

Revision ID: release2_curriculum_review
Revises: release1_job_timestamps
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release2_curriculum_review"
down_revision = "release1_job_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curriculum_evidence_review",
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("source_authoritative", sa.Boolean(), nullable=False),
        sa.Column("extraction_complete", sa.Boolean(), nullable=False),
        sa.Column("module_evidence_complete", sa.Boolean(), nullable=False),
        sa.Column("learning_outcomes_complete", sa.Boolean(), nullable=False),
        sa.Column("completeness_score", sa.Integer(), nullable=False),
        sa.Column("issue_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('validated', 'changes_required', 'rejected')",
            name="ck_curriculum_evidence_review_decision",
        ),
        sa.CheckConstraint(
            "completeness_score >= 0 AND completeness_score <= 100",
            name="ck_curriculum_evidence_review_score",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("review_id"),
    )
    op.create_index("ix_curriculum_evidence_review_document_id", "curriculum_evidence_review", ["document_id"])
    op.create_index("ix_curriculum_evidence_review_version_id", "curriculum_evidence_review", ["version_id"])
    op.create_index("ix_curriculum_evidence_review_decision", "curriculum_evidence_review", ["decision"])
    op.create_index("ix_curriculum_evidence_review_reviewer_id", "curriculum_evidence_review", ["reviewer_id"])
    op.create_index(
        "idx_curriculum_evidence_review_version_created",
        "curriculum_evidence_review",
        ["version_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("curriculum_evidence_review")
