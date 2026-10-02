"""Add the Constitution as the national curriculum-governance context."""

from alembic import op


revision = "release7a_constitution"
down_revision = "release7_curriculum_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO curriculum_governance_evidence (
            evidence_id, tenant_id, programme_id, document_version_id, parent_evidence_id,
            layer, authority, evidence_key, title, identifier,
            official_url, currency_status, verification_status, notes,
            evidence_metadata, created_at, updated_at
        )
        VALUES (
            '71000000-0000-4000-8000-000000000008', NULL, NULL, NULL, NULL,
            'legislation', 'Government of South Africa',
            'za-constitution-1996',
            'Constitution of the Republic of South Africa, 1996',
            'Constitution, 1996',
            'https://www.gov.za/documents/constitution-republic-south-africa-1996',
            'current', 'verified',
            'National constitutional context for further education and higher-education legislation.',
            '{"scope":"shared_national_reference","position":"constitutional_context"}'::jsonb,
            now(), now()
        )
        ON CONFLICT (evidence_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM curriculum_governance_evidence "
        "WHERE evidence_key = 'za-constitution-1996'"
    )
