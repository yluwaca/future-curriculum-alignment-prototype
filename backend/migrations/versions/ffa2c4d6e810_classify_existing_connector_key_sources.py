"""classify existing connector key sources

Revision ID: ffa2c4d6e810
Revises: ff9a1b2c3d44
Create Date: 2026-06-18 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ffa2c4d6e810"
down_revision: Union[str, Sequence[str], None] = "ff9a1b2c3d44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE data_source source
            SET connector_definition_id = definition.connector_definition_id,
                ingestion_mode = definition.ingestion_mode,
                source_format = definition.source_format,
                normaliser_key = definition.normaliser_key
            FROM connector_definition definition
            WHERE source.connector_type = definition.connector_key
              AND source.connector_definition_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE data_source
            SET connector_definition_id = NULL,
                ingestion_mode = 'batch',
                source_format = 'unknown',
                normaliser_key = NULL
            WHERE connector_type IN (
                'lms_connector',
                'sis_connector',
                'erp_connector',
                'professional_body_source',
                'industry_association_source'
            )
            """
        )
    )
