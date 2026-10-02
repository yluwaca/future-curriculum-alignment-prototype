"""seed future ready architecture hooks

Revision ID: c9d6e1f2a830
Revises: b8c5d0e2f719
Create Date: 2026-06-16 22:00:00.000000

"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert


revision: str = "c9d6e1f2a830"
down_revision: Union[str, Sequence[str], None] = "b8c5d0e2f719"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


future_sources = [
    {
        "source_key": "lms_connector",
        "name": "Learning Management System Connector",
        "source_type": "lms",
        "source_category": "institutional",
        "connector_type": "lms_connector",
        "owner": "system",
        "config": {
            "enabled": False,
            "capabilities": [
                "course_catalogue_discovery",
                "module_outline_ingestion",
                "assessment_artifact_metadata",
            ],
        },
    },
    {
        "source_key": "sis_connector",
        "name": "Student Information System Connector",
        "source_type": "sis",
        "source_category": "institutional",
        "connector_type": "sis_connector",
        "owner": "system",
        "config": {
            "enabled": False,
            "capabilities": [
                "programme_catalogue_discovery",
                "enrolment_context_ingestion",
                "department_structure_sync",
            ],
        },
    },
    {
        "source_key": "erp_connector",
        "name": "ERP Connector",
        "source_type": "erp",
        "source_category": "institutional",
        "connector_type": "erp_connector",
        "owner": "system",
        "config": {
            "enabled": False,
            "capabilities": [
                "organisational_unit_sync",
                "planning_reference_data",
                "approved_programme_metadata",
            ],
        },
    },
    {
        "source_key": "professional_body_source",
        "name": "Professional Body Source",
        "source_type": "professional_body",
        "source_category": "reference",
        "connector_type": "professional_body_source",
        "owner": "system",
        "config": {
            "enabled": False,
            "capabilities": [
                "competency_framework_ingestion",
                "accreditation_requirement_tracking",
                "standard_versioning",
            ],
        },
    },
    {
        "source_key": "industry_association_source",
        "name": "Industry Association Source",
        "source_type": "industry_association",
        "source_category": "labour_market",
        "connector_type": "industry_association_source",
        "owner": "system",
        "config": {
            "enabled": False,
            "capabilities": [
                "sector_skill_signal_ingestion",
                "emerging_skill_watchlists",
                "industry_report_ingestion",
            ],
        },
    },
]


def upgrade() -> None:
    data_source = sa.table(
        "data_source",
        sa.column("source_id", sa.String),
        sa.column("source_key", sa.String),
        sa.column("name", sa.String),
        sa.column("source_type", sa.String),
        sa.column("source_category", sa.String),
        sa.column("connector_type", sa.String),
        sa.column("refresh_policy", sa.String),
        sa.column("owner", sa.String),
        sa.column("status", sa.String),
        sa.column("is_authorised", sa.Boolean),
        sa.column("config", sa.JSON),
        sa.column("auth_config", sa.JSON),
    )

    for source in future_sources:
        statement = insert(data_source).values(
            source_id=uuid.uuid4(),
            source_key=source["source_key"],
            name=source["name"],
            source_type=source["source_type"],
            source_category=source["source_category"],
            connector_type=source["connector_type"],
            refresh_policy="manual",
            owner=source["owner"],
            status="planned",
            is_authorised=False,
            config=source["config"],
            auth_config={},
        )
        op.execute(
            statement.on_conflict_do_nothing(index_elements=["source_key"])
        )


def downgrade() -> None:
    keys = [source["source_key"] for source in future_sources]
    data_source = sa.table(
        "data_source",
        sa.column("source_key", sa.String),
    )
    op.execute(data_source.delete().where(data_source.c.source_key.in_(keys)))
