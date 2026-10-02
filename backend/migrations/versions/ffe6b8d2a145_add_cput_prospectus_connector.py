"""add cput prospectus connector

Revision ID: ffe6b8d2a145
Revises: ffd5a7c9e241
Create Date: 2026-06-19 10:00:00.000000

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "ffe6b8d2a145"
down_revision: Union[str, Sequence[str], None] = "ffd5a7c9e241"
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
                :connector_definition_id, 'cput_online_prospectus',
                'CPUT Online Prospectus Connector', 'web_prospectus',
                'manual', 'curriculum', 'html', 'cput_prospectus_v1',
                false, false,
                'Discovers CPUT prospectus courses and imports programme/module structure from public course detail pages.',
                CAST(:capability_profile AS jsonb), CAST(:default_config AS jsonb), 'active'
            )
            ON CONFLICT (connector_key) DO NOTHING
            """
        ),
        {
            "connector_definition_id": str(uuid.uuid4()),
            "capability_profile": json.dumps(
                {
                    "discovers_programmes": True,
                    "extracts_modules": True,
                    "preserves_html": True,
                    "supports_faculty_code": True,
                    "default_faculty_code": "220",
                }
            ),
            "default_config": json.dumps(
                {
                    "institution": "CPUT",
                    "publisher": "Cape Peninsula University of Technology",
                    "source_page": "https://prospectus.cput.ac.za/",
                    "ingestion_group": "curriculum",
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
                :normaliser_definition_id, 'cput_prospectus_v1',
                'CPUT Prospectus Normaliser', '1.0.0',
                'curriculum', 'html', 'curriculum_programme_structure',
                CAST(:supported_record_types AS jsonb), CAST(:transformation_profile AS jsonb),
                CAST(:output_schema AS jsonb), true, 'active',
                'Normalises CPUT online prospectus HTML into programme, year, and module records.'
            )
            ON CONFLICT (normaliser_key, version) DO NOTHING
            """
        ),
        {
            "normaliser_definition_id": str(uuid.uuid4()),
            "supported_record_types": json.dumps(
                [
                    "cput_prospectus_course_index",
                    "cput_prospectus_course_detail",
                    "cput_prospectus_module",
                ]
            ),
            "transformation_profile": json.dumps(
                {
                    "trim_strings": True,
                    "collapse_whitespace": True,
                    "preserve_raw_html": True,
                    "extract_programme_structure": True,
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
        sa.text("DELETE FROM normaliser_definition WHERE normaliser_key = 'cput_prospectus_v1'")
    )
    bind.execute(
        sa.text("DELETE FROM connector_definition WHERE connector_key = 'cput_online_prospectus'")
    )
