"""Add immutable recommendation committee decisions.

Revision ID: release4_rec_governance
Revises: release3_single_active
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release4_rec_governance"
down_revision = "release3_single_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_committee_decision",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_by", sa.String(length=100), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("committee_name", sa.String(length=255), nullable=False),
        sa.Column("meeting_reference", sa.String(length=255), nullable=False),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["decided_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_report_id"], ["generated_report.report_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.recommendation_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index("uq_committee_decision_recommendation", "recommendation_committee_decision", ["recommendation_id"], unique=True)
    op.create_index("ix_committee_decision_evidence_report", "recommendation_committee_decision", ["evidence_report_id"])
    op.create_index("ix_committee_decision_decided_by", "recommendation_committee_decision", ["decided_by"])
    op.create_index("ix_committee_decision_decision", "recommendation_committee_decision", ["decision"])
    op.create_index("ix_committee_decision_evidence_hash", "recommendation_committee_decision", ["evidence_hash"])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_committee_decision_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'committee decisions are append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_committee_decision_immutable
        BEFORE UPDATE OR DELETE ON recommendation_committee_decision
        FOR EACH ROW EXECUTE FUNCTION prevent_committee_decision_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_committee_decision_immutable ON recommendation_committee_decision")
    op.execute("DROP FUNCTION IF EXISTS prevent_committee_decision_mutation()")
    op.drop_table("recommendation_committee_decision")
