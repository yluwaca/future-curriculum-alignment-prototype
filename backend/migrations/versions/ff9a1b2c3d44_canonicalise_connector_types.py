"""canonicalise connector types

Revision ID: ff9a1b2c3d44
Revises: ff4b7c9d0e21
Create Date: 2026-06-18 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ff9a1b2c3d44"
down_revision: Union[str, Sequence[str], None] = "ff4b7c9d0e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    mappings = [
        ("curriculum_pdf", "curriculum_pdf_upload"),
        ("statssa_qlfs", "statssa_qlfs_pdf"),
        ("future_hook", "generic_api_pull"),
    ]
    for legacy_connector_type, connector_key in mappings:
        bind.execute(
            sa.text(
                """
                UPDATE data_source source
                SET connector_type = definition.connector_key,
                    connector_definition_id = definition.connector_definition_id,
                    ingestion_mode = definition.ingestion_mode,
                    source_format = definition.source_format,
                    normaliser_key = definition.normaliser_key
                FROM connector_definition definition
                WHERE source.connector_type = :legacy_connector_type
                  AND definition.connector_key = :connector_key
                """
            ),
            {
                "legacy_connector_type": legacy_connector_type,
                "connector_key": connector_key,
            },
        )
    bind.execute(
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
    bind = op.get_bind()
    mappings = [
        ("curriculum_pdf_upload", "curriculum_pdf"),
        ("statssa_qlfs_pdf", "statssa_qlfs"),
        ("generic_api_pull", "future_hook"),
    ]
    for connector_key, legacy_connector_type in mappings:
        bind.execute(
            sa.text(
                """
                UPDATE data_source
                SET connector_type = :legacy_connector_type
                WHERE connector_type = :connector_key
                """
            ),
            {
                "legacy_connector_type": legacy_connector_type,
                "connector_key": connector_key,
            },
        )
