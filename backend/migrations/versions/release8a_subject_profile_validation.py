"""Add validation fields to curriculum subject profiles.

Revision ID: release8a_profile_validation
Revises: release8_subject_profiles
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "release8a_profile_validation"
down_revision = "release8_subject_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("curriculum_subject_profile", sa.Column("validation_status", sa.String(length=50), nullable=False, server_default="needs_review"))
    op.add_column("curriculum_subject_profile", sa.Column("validated_by", sa.String(length=100), nullable=True))
    op.add_column("curriculum_subject_profile", sa.Column("validation_notes", sa.Text(), nullable=True))
    op.add_column("curriculum_subject_profile", sa.Column("validation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"))
    op.create_index("ix_curriculum_subject_profile_validation_status", "curriculum_subject_profile", ["validation_status"])
    op.create_index("ix_curriculum_subject_profile_validated_by", "curriculum_subject_profile", ["validated_by"])
    op.create_foreign_key("fk_curriculum_subject_profile_validated_by", "curriculum_subject_profile", "jus01_systemidentity", ["validated_by"], ["identity_id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_curriculum_subject_profile_validated_by", "curriculum_subject_profile", type_="foreignkey")
    op.drop_index("ix_curriculum_subject_profile_validated_by", table_name="curriculum_subject_profile")
    op.drop_index("ix_curriculum_subject_profile_validation_status", table_name="curriculum_subject_profile")
    op.drop_column("curriculum_subject_profile", "validation_metadata")
    op.drop_column("curriculum_subject_profile", "validation_notes")
    op.drop_column("curriculum_subject_profile", "validated_by")
    op.drop_column("curriculum_subject_profile", "validation_status")
