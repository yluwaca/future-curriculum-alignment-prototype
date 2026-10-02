"""add ingestion job imported flag

Revision ID: job_imported_01
Revises: job_processed_01
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa

revision = "job_imported_01"
down_revision = "job_processed_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_job",
        sa.Column("imported", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "idx_ingestion_job_imported",
        "ingestion_job",
        ["imported"],
    )


def downgrade() -> None:
    op.drop_index("idx_ingestion_job_imported", table_name="ingestion_job")
    op.drop_column("ingestion_job", "imported")
