"""add job advert file connector

Revision ID: fff7c1d3b260
Revises: ffe6b8d2a145
Create Date: 2026-06-19 19:30:00.000000

"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "fff7c1d3b260"
down_revision: Union[str, Sequence[str], None] = "ffe6b8d2a145"
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
                :connector_definition_id, 'job_advert_file_upload',
                'Job Advert File Upload Connector', 'file_upload',
                'manual', 'current_jobs', 'csv_xlsx_json_txt_pdf', 'job_advert_v1',
                false, false,
                'Imports current job advert datasets from CSV, Excel, JSON, TXT, or PDF files.',
                CAST(:capability_profile AS jsonb), CAST(:default_config AS jsonb), 'active'
            )
            ON CONFLICT (connector_key) DO NOTHING
            """
        ),
        {
            "connector_definition_id": str(uuid.uuid4()),
            "capability_profile": json.dumps(
                {
                    "uploads_files": True,
                    "supports_formats": ["csv", "xlsx", "json", "txt", "pdf"],
                    "maps_job_postings": True,
                    "preserves_raw_payload": True,
                }
            ),
            "default_config": json.dumps(
                {
                    "ingestion_group": "current_jobs",
                    "default_country": "ZA",
                    "default_region": "South Africa",
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
                :normaliser_definition_id, 'job_advert_v1',
                'Job Advert Normaliser', '1.0.0',
                'current_jobs', 'csv_xlsx_json_txt_pdf', 'job_posting',
                CAST(:supported_record_types AS jsonb), CAST(:transformation_profile AS jsonb),
                CAST(:output_schema AS jsonb), true, 'active',
                'Normalises job advert records into job_posting rows for later skill extraction.'
            )
            ON CONFLICT (normaliser_key, version) DO NOTHING
            """
        ),
        {
            "normaliser_definition_id": str(uuid.uuid4()),
            "supported_record_types": json.dumps(["job_advert_record", "job_advert", "job_posting"]),
            "transformation_profile": json.dumps(
                {
                    "trim_strings": True,
                    "collapse_whitespace": True,
                    "extract_skill_text": True,
                    "preserve_raw_payload": True,
                }
            ),
            "output_schema": json.dumps(
                {
                    "required": [
                        "job_id",
                        "job_title",
                        "posted_date",
                        "region",
                        "source",
                    ]
                }
            ),
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM normaliser_definition WHERE normaliser_key = 'job_advert_v1'"))
    bind.execute(sa.text("DELETE FROM connector_definition WHERE connector_key = 'job_advert_file_upload'"))
