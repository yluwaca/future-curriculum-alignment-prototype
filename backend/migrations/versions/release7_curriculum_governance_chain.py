"""Add the national-to-institutional curriculum evidence chain.

Revision ID: release7_curriculum_governance
Revises: release6_data_scientist_role
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release7_curriculum_governance"
down_revision = "release6_data_scientist_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curriculum_governance_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_evidence_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("layer", sa.String(length=50), nullable=False),
        sa.Column("authority", sa.String(length=120), nullable=False),
        sa.Column("evidence_key", sa.String(length=180), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("identifier", sa.String(length=150), nullable=True),
        sa.Column("version_label", sa.String(length=100), nullable=True),
        sa.Column("official_url", sa.String(length=1000), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("currency_status", sa.String(length=30), server_default="unverified", nullable=False),
        sa.Column("verification_status", sa.String(length=30), server_default="unverified", nullable=False),
        sa.Column("nqf_level", sa.Integer(), nullable=True),
        sa.Column("credits", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("verified_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "layer IN ('legislation','nqf','heqsf','che_standard','che_accreditation','dhet_pqm',"
            "'saqa_registration','institutional_programme','module_curriculum')",
            name="ck_curriculum_governance_evidence_curriculum_governance_layer",
        ),
        sa.CheckConstraint(
            "currency_status IN ('current','historical','expired','unknown','unverified')",
            name="ck_curriculum_governance_evidence_curriculum_governance_currency",
        ),
        sa.CheckConstraint(
            "verification_status IN ('unverified','verified','changes_required','rejected')",
            name="ck_curriculum_governance_evidence_curriculum_governance_verification",
        ),
        sa.ForeignKeyConstraint(["parent_evidence_id"], ["curriculum_governance_evidence.evidence_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.tenant_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["programme_id"], ["academic_programme.programme_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_version_id"], ["curriculum_document_version.version_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["verified_by"], ["jus01_systemidentity.identity_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("evidence_id"),
        sa.UniqueConstraint("evidence_key"),
    )
    for column in ("parent_evidence_id", "tenant_id", "programme_id", "document_version_id", "layer", "authority", "evidence_key", "identifier", "currency_status", "verification_status", "verified_by"):
        op.create_index(f"ix_curriculum_governance_evidence_{column}", "curriculum_governance_evidence", [column])
    op.create_index(
        "idx_curriculum_governance_tenant_layer",
        "curriculum_governance_evidence",
        ["tenant_id", "layer", "verification_status"],
    )

    op.execute(
        """
        INSERT INTO curriculum_governance_evidence
          (evidence_id, layer, authority, evidence_key, title, identifier, official_url,
           currency_status, verification_status, notes, evidence_metadata)
        VALUES
          ('71000000-0000-4000-8000-000000000001','legislation','South African Government',
           'za-higher-education-act','Higher Education Act 101 of 1997','Act 101 of 1997',
           'https://www.gov.za/documents/higher-education-act','current','verified',
           'National legislative context; amendments and applicability must be checked for each review date.',
           '{"scope":"shared","role":"legal_context"}'),
          ('71000000-0000-4000-8000-000000000002','legislation','South African Government',
           'za-nqf-act','National Qualifications Framework Act 67 of 2008','Act 67 of 2008',
           'https://www.gov.za/documents/national-qualifications-framework-act','current','verified',
           'National legislative context for the NQF.',
           '{"scope":"shared","role":"legal_context"}'),
          ('71000000-0000-4000-8000-000000000003','nqf','SAQA',
           'za-nqf','National Qualifications Framework','NQF',
           'https://www.saqa.org.za/','current','verified',
           'National framework reference. Qualification-specific registration is recorded separately.',
           '{"scope":"shared","role":"national_framework"}'),
          ('71000000-0000-4000-8000-000000000004','heqsf','CHE',
           'za-heqsf','Higher Education Qualifications Sub-Framework','HEQSF',
           'https://www.che.ac.za/','unverified','unverified',
           'The applicable HEQSF edition and transition rules must be confirmed before programme evaluation.',
           '{"scope":"shared","role":"qualification_architecture"}'),
          ('71000000-0000-4000-8000-000000000005','che_standard','CHE',
           'za-che-qualification-standards','CHE Framework for Qualification Standards in Higher Education',NULL,
           'https://www.che.ac.za/publications/frameworks/framework-qualification-standards-higher-education',
           'current','verified',
           'Framework reference only; add the qualification-type standard and accreditation evidence applicable to a programme.',
           '{"scope":"shared","role":"quality_standard"}'),
          ('71000000-0000-4000-8000-000000000006','dhet_pqm','DHET',
           'za-dhet-pqm','DHET Programme and Qualification Mix approval evidence',NULL,
           'https://www.dhet.gov.za/','unverified','unverified',
           'Institution-specific PQM approval must be supplied and verified; this record is only the national layer placeholder.',
           '{"scope":"shared","role":"institutional_mandate"}'),
          ('71000000-0000-4000-8000-000000000007','saqa_registration','SAQA',
           'za-saqa-registration','SAQA registered qualification record',NULL,
           'https://regqs.saqa.org.za/','unverified','unverified',
           'Create one evidence record per qualification with SAQA ID, NQF level, credits, status and registration dates.',
           '{"scope":"shared","role":"qualification_registration"}')
        """
    )


def downgrade() -> None:
    op.drop_table("curriculum_governance_evidence")
