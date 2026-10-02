"""Add structured curriculum subject profiles.

Revision ID: release8_subject_profiles
Revises: release7a_constitution
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "release8_subject_profiles"
down_revision = "release7a_constitution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curriculum_subject_profile",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("institution", sa.String(length=180), nullable=True),
        sa.Column("faculty", sa.String(length=180), nullable=True),
        sa.Column("department", sa.String(length=180), nullable=True),
        sa.Column("programme_name", sa.String(length=255), nullable=True),
        sa.Column("programme_code", sa.String(length=100), nullable=True),
        sa.Column("qualification_type", sa.String(length=120), nullable=True),
        sa.Column("subject_code", sa.String(length=50), nullable=False),
        sa.Column("subject_name", sa.String(length=255), nullable=False),
        sa.Column("subject_year", sa.Integer(), nullable=True),
        sa.Column("nqf_level", sa.Integer(), nullable=True),
        sa.Column("credits", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("prerequisites", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("articulation", sa.Text(), nullable=True),
        sa.Column("learning_outcomes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("assessment_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("topic_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("extracted_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("source_version_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("source_chunk_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("extraction_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["programme_id"], ["academic_programme.programme_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["module_id"], ["curriculum_module.module_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.UniqueConstraint("version_id", "subject_code", name="uq_curriculum_subject_profile_version_subject"),
    )
    op.create_index("idx_curriculum_subject_profile_subject", "curriculum_subject_profile", ["subject_code", "subject_year"])
    op.create_index("idx_curriculum_subject_profile_programme", "curriculum_subject_profile", ["programme_name", "subject_code"])
    for column in ["document_id", "version_id", "tenant_id", "programme_id", "module_id", "institution", "faculty", "department", "programme_name", "programme_code", "qualification_type", "subject_code", "subject_year", "nqf_level", "status"]:
        op.create_index(f"ix_curriculum_subject_profile_{column}", "curriculum_subject_profile", [column])


def downgrade() -> None:
    op.drop_table("curriculum_subject_profile")


