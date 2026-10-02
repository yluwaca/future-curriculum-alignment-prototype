"""add che vitalstats connector

Revision ID: ffd5a7c9e241
Revises: ffc4e6f8b130
Create Date: 2026-06-18 12:10:00.000000

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "ffd5a7c9e241"
down_revision: Union[str, Sequence[str], None] = "ffc4e6f8b130"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO connector_definition (
                connector_definition_id, connector_key, name, connector_family,
                ingestion_mode, source_category, source_format, normaliser_key,
                is_streaming_capable, requires_auth, description,
                capability_profile, default_config, status
            )
            VALUES (
                :connector_definition_id, 'che_vitalstats_pdf',
                'CHE VitalStats PDF Connector', 'pdf_discovery_download',
                'scheduled', 'higher_education_context', 'pdf', 'che_vitalstats_v1',
                false, false,
                'Discover, download, and parse CHE VitalStats higher-education context publications.',
                CAST(:capability_profile AS jsonb), CAST(:default_config AS jsonb), 'active'
            )
            ON CONFLICT (connector_key) DO NOTHING
            """
        ),
        {
            "connector_definition_id": str(uuid.uuid4()),
            "capability_profile": json.dumps(
                {
                    "discovers_publications": True,
                    "downloads_pdfs": True,
                    "extracts_tables": True,
                    "context_domain": "higher_education_supply",
                }
            ),
            "default_config": json.dumps(
                {
                    "source_page": "https://www.che.ac.za/publications/vital-stats",
                    "publisher": "Council on Higher Education",
                    "ingestion_group": "higher_education_context",
                }
            ),
        },
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO normaliser_definition (
                normaliser_definition_id, normaliser_key, name, version,
                source_category, input_format, output_record_type,
                supported_record_types, transformation_profile, output_schema,
                is_default, status, description
            )
            VALUES (
                :normaliser_definition_id, 'che_vitalstats_v1',
                'CHE VitalStats Normaliser', '1.0.0',
                'higher_education_context', 'pdf', 'higher_education_supply_context',
                CAST(:supported_record_types AS jsonb), CAST(:transformation_profile AS jsonb),
                CAST(:output_schema AS jsonb), true, 'active',
                'Normalises CHE VitalStats PDF metadata and extracted tables into higher-education supply/context records.'
            )
            ON CONFLICT (normaliser_key, version) DO NOTHING
            """
        ),
        {
            "normaliser_definition_id": str(uuid.uuid4()),
            "supported_record_types": json.dumps(["che_vitalstats_pdf", "che_vitalstats_table"]),
            "transformation_profile": json.dumps(
                {
                    "trim_strings": True,
                    "collapse_whitespace": True,
                    "drop_empty_rows": True,
                    "preserve_raw_payload": True,
                    "clean_numeric_values": True,
                }
            ),
            "output_schema": json.dumps(
                {
                    "required": [
                        "record_type",
                        "source_record_id",
                        "normalised_payload",
                        "raw_payload",
                    ]
                }
            ),
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM normaliser_definition WHERE normaliser_key = 'che_vitalstats_v1'")
    )
    bind.execute(
        sa.text("DELETE FROM connector_definition WHERE connector_key = 'che_vitalstats_pdf'")
    )
