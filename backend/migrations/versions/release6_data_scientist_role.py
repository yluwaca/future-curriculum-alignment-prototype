"""Add the missing data scientist RBAC role.

Revision ID: release6_data_scientist_role
Revises: release5_monitoring_alerts
"""

from alembic import op


revision = "release6_data_scientist_role"
down_revision = "release5_monitoring_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO sec02_role (role_id, role_name, description, is_active)
        VALUES (
            'data_scientist',
            'Data Scientist',
            'Model Lab, candidate training and validation, plus Data Operations',
            true
        )
        ON CONFLICT (role_id) DO UPDATE
        SET role_name = EXCLUDED.role_name,
            description = EXCLUDED.description,
            is_active = true
        """
    )
    op.execute(
        """
        UPDATE sec02_role
        SET description = 'Review, independent labelling, and Data Operations'
        WHERE role_id = 'analyst'
        """
    )
    op.execute(
        """
        UPDATE sec02_role
        SET description = 'Read-only access to decision dashboards and reports'
        WHERE role_id = 'viewer'
        """
    )
    op.execute(
        """
        INSERT INTO sec04_rolepermission (role_id, permission_id, is_active)
        SELECT 'data_scientist', permission_id, true
        FROM sec03_permission
        WHERE permission_id IN (
            'dataset.read',
            'dataset.write',
            'model.run',
            'model.train'
        )
        ON CONFLICT (role_id, permission_id) DO UPDATE
        SET is_active = true
        """
    )
    op.execute(
        """
        DELETE FROM sec04_rolepermission
        WHERE role_id = 'analyst'
          AND permission_id = 'model.train'
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM sec04_rolepermission WHERE role_id = 'data_scientist'"
    )
    op.execute(
        "DELETE FROM sec02_role WHERE role_id = 'data_scientist'"
    )
