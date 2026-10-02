"""add timestamp defaults to operational jobs

Revision ID: release1_job_timestamps
Revises: release1_operational_jobs
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "release1_job_timestamps"
down_revision: Union[str, Sequence[str], None] = "release1_operational_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "operational_job",
        "created_at",
        server_default=sa.func.now(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "operational_job",
        "updated_at",
        server_default=sa.func.now(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "operational_job",
        "created_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "operational_job",
        "updated_at",
        server_default=None,
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
