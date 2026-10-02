"""add ingestion job processed flag

Revision ID: job_processed_01
Revises: add_curriculum_alignment_score
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa

revision = "job_processed_01"
down_revision = "add_curriculum_alignment_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_job",
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "idx_ingestion_job_processed",
        "ingestion_job",
        ["processed"],
    )


def downgrade() -> None:
    op.drop_index("idx_ingestion_job_processed", table_name="ingestion_job")
    op.drop_column("ingestion_job", "processed")
