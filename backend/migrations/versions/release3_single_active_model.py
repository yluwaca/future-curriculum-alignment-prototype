"""Enforce one active registry entry per model type.

Revision ID: release3_single_active
Revises: release2_label_snapshots
"""

from alembic import op


revision = "release3_single_active"
down_revision = "release2_label_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_model_registry_one_active_type
        ON model_registry (model_type)
        WHERE is_active = 1
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_model_registry_one_active_type")
