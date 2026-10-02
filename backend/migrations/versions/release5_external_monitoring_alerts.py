"""Add durable operational monitoring alerts.

Revision ID: release5_monitoring_alerts
Revises: release5_tenant_identity
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release5_monitoring_alerts"
down_revision = "release5_tenant_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_alert",
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("alert_key", sa.String(length=180), nullable=False),
        sa.Column("component", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=100), nullable=True),
        sa.Column("acknowledgement_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_status", sa.String(length=30), nullable=False, server_default="not_configured"),
        sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_notification_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    op.create_index("ix_system_alert_tenant_id", "system_alert", ["tenant_id"])
    op.create_index("ix_system_alert_alert_key", "system_alert", ["alert_key"])
    op.create_index("ix_system_alert_component", "system_alert", ["component"])
    op.create_index("ix_system_alert_severity", "system_alert", ["severity"])
    op.create_index("ix_system_alert_status", "system_alert", ["status"])
    op.create_index("ix_system_alert_last_detected_at", "system_alert", ["last_detected_at"])
    op.create_index("idx_system_alert_state_severity", "system_alert", ["status", "severity"])
    op.create_index("idx_system_alert_tenant_key", "system_alert", ["tenant_id", "alert_key"])


def downgrade() -> None:
    op.drop_table("system_alert")
