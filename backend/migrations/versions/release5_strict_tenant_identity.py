"""Bind human identities to tenants and seed the development institution.

Revision ID: release5_tenant_identity
Revises: release4_rec_governance
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "release5_tenant_identity"
down_revision = "release4_rec_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jus01_systemidentity",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_identity_tenant_id", "jus01_systemidentity", "tenant",
        ["tenant_id"], ["tenant_id"], ondelete="RESTRICT",
    )
    op.create_index("ix_jus01_systemidentity_tenant_id", "jus01_systemidentity", ["tenant_id"])
    op.execute(
        """
        INSERT INTO tenant (
          tenant_id, tenant_key, name, tenant_type, country, region,
          status, description, tenant_metadata, created_at, updated_at
        )
        VALUES (
          'c0000000-0000-4000-8000-000000000001',
          'cput', 'Cape Peninsula University of Technology',
          'institution', 'South Africa', 'Western Cape', 'active',
          'Default institution for the current CPUT development deployment.',
          '{"seeded_by":"release5_tenant_identity"}'::jsonb, now(), now()
        )
        ON CONFLICT (tenant_key) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE jus01_systemidentity
        SET tenant_id = (
          SELECT tenant_id FROM tenant WHERE tenant_key = 'cput'
        )
        WHERE tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE data_source
        SET tenant_id = (SELECT tenant_id FROM tenant WHERE tenant_key = 'cput'),
            source_scope = 'tenant'
        WHERE tenant_id IS NULL AND source_category = 'curriculum';

        UPDATE curriculum_document
        SET tenant_id = (SELECT tenant_id FROM tenant WHERE tenant_key = 'cput')
        WHERE tenant_id IS NULL;

        UPDATE curriculum_document_version v
        SET tenant_id = d.tenant_id
        FROM curriculum_document d
        WHERE v.document_id = d.document_id AND v.tenant_id IS NULL;

        UPDATE document_chunk c
        SET tenant_id = v.tenant_id
        FROM curriculum_document_version v
        WHERE c.version_id = v.version_id AND c.tenant_id IS NULL;

        UPDATE ingestion_job j
        SET tenant_id = s.tenant_id
        FROM data_source s
        WHERE j.source_id = s.source_id AND j.tenant_id IS NULL
          AND s.tenant_id IS NOT NULL;

        UPDATE raw_ingestion_record r
        SET tenant_id = j.tenant_id
        FROM ingestion_job j
        WHERE r.job_id = j.job_id AND r.tenant_id IS NULL
          AND j.tenant_id IS NOT NULL;

        UPDATE cleaned_ingestion_record c
        SET tenant_id = j.tenant_id
        FROM ingestion_job j
        WHERE c.job_id = j.job_id AND c.tenant_id IS NULL
          AND j.tenant_id IS NOT NULL;

        UPDATE pipeline_run
        SET tenant_id = (SELECT tenant_id FROM tenant WHERE tenant_key = 'cput'),
            run_scope = 'tenant'
        WHERE tenant_id IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_jus01_systemidentity_tenant_id", table_name="jus01_systemidentity")
    op.drop_constraint("fk_identity_tenant_id", "jus01_systemidentity", type_="foreignkey")
    op.drop_column("jus01_systemidentity", "tenant_id")
