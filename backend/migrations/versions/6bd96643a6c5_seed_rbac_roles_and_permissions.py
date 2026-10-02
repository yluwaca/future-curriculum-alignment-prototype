"""seed rbac roles and permissions

Revision ID: 6bd96643a6c5
Revises: 74de72914271
Create Date: 2026-03-08 21:22:55.389920

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6bd96643a6c5'
down_revision: Union[str, Sequence[str], None] = '74de72914271'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade(): 
    # -------------------------
    # Roles
    # -------------------------
    op.bulk_insert(
        sa.table(
            "sec02_role",
            sa.column("role_id", sa.String),
            sa.column("role_name", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {
                "role_id": "admin",
                "role_name": "Administrator",
                "description": "Full system access",
            },
            {
                "role_id": "analyst",
                "role_name": "Analyst",
                "description": "Can run models and read datasets",
            },
            {
                "role_id": "viewer",
                "role_name": "Viewer",
                "description": "Read-only access",
            },
        ],
    )

    # -------------------------
    # Permissions
    # -------------------------
    op.bulk_insert(
        sa.table(
            "sec03_permission",
            sa.column("permission_id", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"permission_id": "dataset.read", "description": "Read datasets"},
            {"permission_id": "dataset.write", "description": "Modify datasets"},
            {"permission_id": "model.run", "description": "Execute predictive models"},
            {"permission_id": "model.train", "description": "Train predictive models"},
            {"permission_id": "system.admin", "description": "System administration"},
        ],
    )

    # -------------------------
    # Role → Permission mapping
    # -------------------------
    op.bulk_insert(
        sa.table(
            "sec04_rolepermission",
            sa.column("role_id", sa.String),
            sa.column("permission_id", sa.String),
        ),
        [

            # ADMIN
            {"role_id": "admin", "permission_id": "dataset.read"},
            {"role_id": "admin", "permission_id": "dataset.write"},
            {"role_id": "admin", "permission_id": "model.run"},
            {"role_id": "admin", "permission_id": "model.train"},
            {"role_id": "admin", "permission_id": "system.admin"},

            # ANALYST
            {"role_id": "analyst", "permission_id": "dataset.read"},
            {"role_id": "analyst", "permission_id": "model.run"},
            {"role_id": "analyst", "permission_id": "model.train"},

            # VIEWER
            {"role_id": "viewer", "permission_id": "dataset.read"},
        ],
    )


def downgrade():
    op.execute("DELETE FROM sec04_rolepermission")
    op.execute("DELETE FROM sec03_permission")
    op.execute("DELETE FROM sec02_role")
