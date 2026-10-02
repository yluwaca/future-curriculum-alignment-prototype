"""Add labour-market offline-readiness indexes.

Revision ID: release9b_readiness_indexes
Revises: release9a_curriculum_approver
Create Date: 2026-09-09
"""

from alembic import op

revision = "release9b_readiness_indexes"
down_revision = "release9a_curriculum_approver"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_jobposting_source",
        "job_posting",
        ["source"],
        unique=False,
    )
    op.create_index(
        "idx_jobposting_source_updated",
        "job_posting",
        ["source_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_skill_mapping_domain_status",
        "skill_mapping",
        ["source_domain", "mapping_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_skill_mapping_domain_status", table_name="skill_mapping")
    op.drop_index("idx_jobposting_source_updated", table_name="job_posting")
    op.drop_index("idx_jobposting_source", table_name="job_posting")