"""add immutable reviewed-label dataset snapshots

Revision ID: release2_label_snapshots
Revises: release2_alignment_labels
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release2_label_snapshots"
down_revision = "release2_alignment_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "label_dataset_snapshot",
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_version", sa.String(length=100), nullable=False),
        sa.Column("dataset_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=30), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=False),
        sa.Column("label_rubric", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inclusion_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("exclusion_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dataset_card", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["locked_by"], ["jus01_systemidentity.identity_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint("snapshot_version"),
        sa.UniqueConstraint("dataset_fingerprint"),
    )
    op.create_index("ix_label_dataset_snapshot_dataset_fingerprint", "label_dataset_snapshot", ["dataset_fingerprint"])
    op.create_index("ix_label_dataset_snapshot_lifecycle_state", "label_dataset_snapshot", ["lifecycle_state"])
    op.create_index("idx_label_dataset_snapshot_state_created", "label_dataset_snapshot", ["lifecycle_state", "created_at"])

    op.create_table(
        "label_dataset_snapshot_row",
        sa.Column("snapshot_row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_window_hash", sa.String(length=64), nullable=False),
        sa.Column("curriculum_evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("final_alignment_label", sa.Integer(), nullable=False),
        sa.Column("label_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewer_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["label_dataset_snapshot.snapshot_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("snapshot_row_id"),
        sa.UniqueConstraint("snapshot_id", "row_index", name="uq_label_dataset_snapshot_row_index"),
        sa.UniqueConstraint("snapshot_id", "task_id", name="uq_label_dataset_snapshot_row_task"),
    )
    op.create_index("ix_label_dataset_snapshot_row_snapshot_id", "label_dataset_snapshot_row", ["snapshot_id"])
    op.create_index("ix_label_dataset_snapshot_row_task_id", "label_dataset_snapshot_row", ["task_id"])

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_locked_label_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Locked label dataset snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_label_snapshot_no_update_delete
        BEFORE UPDATE OR DELETE ON label_dataset_snapshot
        FOR EACH ROW EXECUTE FUNCTION prevent_locked_label_snapshot_mutation();
    """)
    op.execute("""
        CREATE TRIGGER trg_label_snapshot_row_no_update_delete
        BEFORE UPDATE OR DELETE ON label_dataset_snapshot_row
        FOR EACH ROW EXECUTE FUNCTION prevent_locked_label_snapshot_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_label_snapshot_row_no_update_delete ON label_dataset_snapshot_row")
    op.execute("DROP TRIGGER IF EXISTS trg_label_snapshot_no_update_delete ON label_dataset_snapshot")
    op.execute("DROP FUNCTION IF EXISTS prevent_locked_label_snapshot_mutation")
    op.drop_table("label_dataset_snapshot_row")
    op.drop_table("label_dataset_snapshot")
