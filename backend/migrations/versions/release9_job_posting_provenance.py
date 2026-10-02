"""Add relational provenance to job postings.

Revision ID: release9_job_provenance
Revises: release8a_profile_validation
Create Date: 2026-08-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "release9_job_provenance"
down_revision = "release8a_profile_validation"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("job_posting", sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("job_posting", sa.Column("ingestion_job_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_job_posting_source_id", "job_posting", "data_source", ["source_id"], ["source_id"], ondelete="SET NULL")
    op.create_foreign_key("fk_job_posting_ingestion_job_id", "job_posting", "ingestion_job", ["ingestion_job_id"], ["job_id"], ondelete="SET NULL")
    op.create_index("ix_job_posting_source_id", "job_posting", ["source_id"])
    op.create_index("ix_job_posting_ingestion_job_id", "job_posting", ["ingestion_job_id"])
    # No trustworthy historical ingestion-job key exists. Keep that FK NULL;
    # recover the registered source link deterministically.
    op.execute("""
        UPDATE job_posting AS jp
        SET source_id = ds.source_id
        FROM data_source AS ds
        WHERE jp.source = 'generic_import'
          AND jp.source_id IS NULL
          AND ds.source_key = 'generic_current_jobs_linkedin_linkedin'
    """)

def downgrade() -> None:
    op.drop_index("ix_job_posting_ingestion_job_id", table_name="job_posting")
    op.drop_index("ix_job_posting_source_id", table_name="job_posting")
    op.drop_constraint("fk_job_posting_ingestion_job_id", "job_posting", type_="foreignkey")
    op.drop_constraint("fk_job_posting_source_id", "job_posting", type_="foreignkey")
    op.drop_column("job_posting", "ingestion_job_id")
    op.drop_column("job_posting", "source_id")
