"""Add strict curriculum-approver academic governance.

Revision ID: release9a_curriculum_approver
Revises: release9_job_provenance
Create Date: 2026-08-22
"""

from alembic import op

revision = "release9a_curriculum_approver"
down_revision = "release9_job_provenance"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
        INSERT INTO sec02_role (role_id, role_name, description, is_active, is_system_role)
        VALUES ('curriculum_approver', 'Curriculum Approver',
          'Academic reviewer with exclusive authority over curriculum recommendation decisions', true, true)
        ON CONFLICT (role_id) DO UPDATE SET role_name=EXCLUDED.role_name,
          description=EXCLUDED.description, is_active=true, is_system_role=true
    """)
    op.execute("""
        INSERT INTO sec03_permission (permission_id, permission_name, description, resource, is_active, is_system_permission)
        VALUES ('recommendation.academic_approve', 'recommendation.academic_approve',
          'Approve, reject, modify, or record a committee decision for an academic curriculum recommendation',
          'recommendation', true, true)
        ON CONFLICT (permission_id) DO UPDATE SET permission_name=EXCLUDED.permission_name,
          description=EXCLUDED.description, resource=EXCLUDED.resource,
          is_active=true, is_system_permission=true
    """)
    # Ensure the permission is exclusive even in manually modified environments.
    op.execute("DELETE FROM sec04_rolepermission WHERE permission_id = 'recommendation.academic_approve'")
    op.execute("""
        INSERT INTO sec04_rolepermission (role_id, permission_id, is_active)
        VALUES ('curriculum_approver', 'recommendation.academic_approve', true)
    """)

def downgrade() -> None:
    op.execute("DELETE FROM sec04_rolepermission WHERE permission_id = 'recommendation.academic_approve'")
    op.execute("DELETE FROM sec03_permission WHERE permission_id = 'recommendation.academic_approve'")
    op.execute("DELETE FROM sec05_userrole WHERE role_id = 'curriculum_approver'")
    op.execute("DELETE FROM sec02_role WHERE role_id = 'curriculum_approver'")
