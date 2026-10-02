"""Add ESCO bundle provenance, review-dataset modes, and OFO acquisition type.

Revision ID: release11_final_completion_2026
Revises: release10_dhet_ofo
Create Date: 2026-09-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "release11_final_completion_2026"
down_revision = "release10_dhet_ofo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "esco_bundle",
        sa.Column("bundle_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_version", sa.String(50), nullable=False, server_default="1.2.0"),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("licence", sa.String(300), nullable=False),
        sa.Column("source_label", sa.String(300), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending_validation"),
        sa.Column("files", JSONB(), nullable=False, server_default="[]"),
        sa.Column("row_counts", JSONB(), nullable=False, server_default="{}"),
        sa.Column("file_checksums", JSONB(), nullable=False, server_default="{}"),
        sa.Column("validation_errors", JSONB(), nullable=False, server_default="[]"),
        sa.Column("expected_files", JSONB(), nullable=False, server_default="[]"),
        sa.Column("predicted", JSONB(), nullable=False, server_default="{}"),
        sa.Column("imported_counts", JSONB(), nullable=False, server_default="{}"),
        sa.Column("not_modelled_files", JSONB(), nullable=False, server_default="[]"),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("imported_by", sa.String(100), nullable=True),
        sa.Column("partial_file", sa.String(300), nullable=True),
        sa.Column("failed_file", sa.String(300), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("contributions", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_esco_bundle_status_created", "esco_bundle", ["status", "created_at"])
    op.create_index("idx_esco_bundle_run_id", "esco_bundle", ["run_id"], unique=True)

    op.add_column("esco_skill", sa.Column("bundle_id", UUID(as_uuid=True), sa.ForeignKey("esco_bundle.bundle_id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_esco_skill_bundle_id", "esco_skill", ["bundle_id"])
    op.add_column("esco_occupation", sa.Column("bundle_id", UUID(as_uuid=True), sa.ForeignKey("esco_bundle.bundle_id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_esco_occupation_bundle_id", "esco_occupation", ["bundle_id"])
    op.add_column("esco_occupation_skill_link", sa.Column("bundle_id", UUID(as_uuid=True), sa.ForeignKey("esco_bundle.bundle_id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_esco_occ_skill_link_bundle_id", "esco_occupation_skill_link", ["bundle_id"])

    op.add_column("dhet_ofo_acquisition", sa.Column("acquisition_type", sa.String(30), nullable=False, server_default="official"))
    op.create_index("ix_dhet_ofo_acq_type_status", "dhet_ofo_acquisition", ["acquisition_type", "status"])

    op.add_column("label_dataset_snapshot", sa.Column("dataset_mode", sa.String(40), nullable=False, server_default="technical_uat_researcher_operated"))
    op.add_column("label_dataset_snapshot", sa.Column("sample_definition", JSONB(), nullable=False, server_default="{}"))
    op.add_column("label_dataset_snapshot", sa.Column("agreement_statistics", JSONB(), nullable=False, server_default="{}"))
    op.create_index("ix_label_dataset_snapshot_mode_state", "label_dataset_snapshot", ["dataset_mode", "lifecycle_state"])

    op.add_column("alignment_expert_label", sa.Column("reviewer_persona", sa.String(40), nullable=False, server_default="researcher_operated_uat"))
    op.create_index("ix_alignment_expert_label_persona", "alignment_expert_label", ["reviewer_persona"])

    op.add_column("alignment_review_task", sa.Column("sample_seed", sa.String(64), nullable=True))
    op.add_column("alignment_review_task", sa.Column("stratum", sa.String(120), nullable=True))
    op.add_column("alignment_review_task", sa.Column("dataset_mode", sa.String(40), nullable=False, server_default="technical_uat_researcher_operated"))
    op.create_index("ix_alignment_review_task_seed", "alignment_review_task", ["sample_seed"])
    op.create_index("ix_alignment_review_task_stratum", "alignment_review_task", ["stratum"])


def downgrade() -> None:
    op.drop_index("ix_alignment_review_task_stratum", table_name="alignment_review_task")
    op.drop_index("ix_alignment_review_task_seed", table_name="alignment_review_task")
    op.drop_column("alignment_review_task", "dataset_mode")
    op.drop_column("alignment_review_task", "stratum")
    op.drop_column("alignment_review_task", "sample_seed")

    op.drop_index("ix_alignment_expert_label_persona", table_name="alignment_expert_label")
    op.drop_column("alignment_expert_label", "reviewer_persona")

    op.drop_index("ix_label_dataset_snapshot_mode_state", table_name="label_dataset_snapshot")
    op.drop_column("label_dataset_snapshot", "agreement_statistics")
    op.drop_column("label_dataset_snapshot", "sample_definition")
    op.drop_column("label_dataset_snapshot", "dataset_mode")

    op.drop_index("ix_dhet_ofo_acq_type_status", table_name="dhet_ofo_acquisition")
    op.drop_column("dhet_ofo_acquisition", "acquisition_type")

    op.drop_index("ix_esco_occ_skill_link_bundle_id", table_name="esco_occupation_skill_link")
    op.drop_column("esco_occupation_skill_link", "bundle_id")
    op.drop_index("ix_esco_occupation_bundle_id", table_name="esco_occupation")
    op.drop_column("esco_occupation", "bundle_id")
    op.drop_index("ix_esco_skill_bundle_id", table_name="esco_skill")
    op.drop_column("esco_skill", "bundle_id")

    op.drop_index("idx_esco_bundle_run_id", table_name="esco_bundle")
    op.drop_index("idx_esco_bundle_status_created", table_name="esco_bundle")
    op.drop_table("esco_bundle")