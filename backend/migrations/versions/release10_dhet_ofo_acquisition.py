"""Add DHET OFO 2021 acquisition, evidence mapping, and review audit tables.

Revision ID: release10_dhet_ofo
Revises: release9b_readiness_indexes
Create Date: 2026-09-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "release10_dhet_ofo"
down_revision = "release9b_readiness_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dhet_ofo_acquisition",
        sa.Column("acquisition_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_key", sa.String(100), nullable=False, server_default="dhet_ofo_2021"),
        sa.Column("method", sa.String(20), nullable=False, server_default="download"),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("resolved_url", sa.String(1000), nullable=True),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("stored_path", sa.String(1000), nullable=True),
        sa.Column("operator_id", sa.String(100), nullable=True),
        sa.Column("operator_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending_validation"),
        sa.Column("validation_errors", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("data_rows", sa.Integer(), nullable=True),
        sa.Column("imported_rows", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_dhet_ofo_acq_sha", "dhet_ofo_acquisition", ["sha256", "status"])
    op.create_index("idx_dhet_ofo_acq_source_time", "dhet_ofo_acquisition", ["source_key", "retrieved_at"])

    op.create_table(
        "ofo_evidence_mapping",
        sa.Column("mapping_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_record_id", sa.String(255), nullable=True),
        sa.Column("source_domain", sa.String(100), nullable=False),
        sa.Column("source_entity_type", sa.String(100), nullable=True),
        sa.Column("source_entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column("duties_text", sa.Text(), nullable=True),
        sa.Column("education_text", sa.Text(), nullable=True),
        sa.Column("experience_text", sa.Text(), nullable=True),
        sa.Column("skills_text", sa.Text(), nullable=True),
        sa.Column("ofo_occupation_id", UUID(as_uuid=True), sa.ForeignKey("ofo_occupation.ofo_occupation_id", ondelete="SET NULL"), nullable=True),
        sa.Column("ofo_code", sa.String(20), nullable=True),
        sa.Column("occupation_title", sa.String(255), nullable=True),
        sa.Column("canonical_skill_id", UUID(as_uuid=True), sa.ForeignKey("skill.skill_id", ondelete="SET NULL"), nullable=True),
        sa.Column("method", sa.String(100), nullable=False, server_default="evidence_semantic"),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("mapping_status", sa.String(50), nullable=False, server_default="candidate"),
        sa.Column("reviewer_id", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("mapping_metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ofo_evidence_mapping_status_domain", "ofo_evidence_mapping", ["mapping_status", "source_domain"])
    op.create_index("idx_ofo_evidence_mapping_source", "ofo_evidence_mapping", ["source_record_id", "source_entity_id"])

    op.create_table(
        "ofo_evidence_mapping_review_event",
        sa.Column("review_event_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("mapping_id", UUID(as_uuid=True), sa.ForeignKey("ofo_evidence_mapping.mapping_id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_status", sa.String(50), nullable=False),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reviewer_id", sa.String(100), sa.ForeignKey("jus01_systemidentity.identity_id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("ofo_code_before", sa.String(20), nullable=True),
        sa.Column("ofo_code_after", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ofo_evidence_mapping_event_created", "ofo_evidence_mapping_review_event", ["mapping_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ofo_evidence_mapping_review_event")
    op.drop_table("ofo_evidence_mapping")
    op.drop_table("dhet_ofo_acquisition")