import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool
from alembic import context

# -------------------------------------------------------------------
# Load environment variables
# -------------------------------------------------------------------
load_dotenv()

# Alembic Config object
config = context.config

# -------------------------------------------------------------------
# Load DATABASE_URL from .env
# -------------------------------------------------------------------
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is not set in environment")

config.set_main_option("sqlalchemy.url", database_url)

# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# -------------------------------------------------------------------
# Import SQLAlchemy Base and ALL models
# IMPORTANT: Every model that Alembic should track MUST be imported here
# so that Base.metadata is fully populated before migration generation.
# -------------------------------------------------------------------
from app.models.base import Base

# Core & Security Models
from app.models import user
from app.models import tenant
from app.models import auth_token
from app.models import audit_event

# RBAC Models
from app.models import role
from app.models import permission
from app.models import user_role
from app.models import role_permission

# Predictive Models (New)
from app.models import curriculum_module
from app.models import academic_faculty
from app.models import academic_department
from app.models import academic_programme
from app.models import curriculum_document
from app.models import curriculum_document_version
from app.models import document_chunk
from app.models import embedding_model
from app.models import vector_embedding
from app.models import semantic_search_query
from app.models import skill
from app.models import esco_skill
from app.models import esco_bundle
from app.models import skill_alias
from app.models import skill_mapping
from app.models import alignment_score
from app.models import forecast
from app.models import recommendation
from app.models import recommendation_explanation
from app.models import recommendation_review
from app.models import recommendation_feedback
from app.models import recommendation_status_history
from app.models import job_posting
from app.models import predictive_output
from app.models import data_source
from app.models import connector_definition
from app.models import ingestion_job
from app.models import ingestion_failure_event
from app.models import raw_ingestion_record
from app.models import extracted_table
from app.models import extracted_table_row
from app.models import data_lineage_event
from app.models import ingestion_contract
from app.models import normaliser_definition
from app.models import data_quality_rule
from app.models import data_quality_check
from app.models import cleaned_ingestion_record
from app.models import labour_market_indicator
from app.models import labour_market_observation
from app.models import labour_market_trend
from app.models import labour_market_signal
from app.models import skill_demand_evidence
from app.models import generated_report
from app.models import pipeline_run
from app.models import pipeline_stage_run
from app.models import operational_job
from app.models import dhet_ofo
from app.models import alignment_review_task
from app.models import alignment_expert_label
from app.models import label_dataset_snapshot

# This metadata object is used by Alembic to detect schema changes
target_metadata = Base.metadata

# -------------------------------------------------------------------
# Migration Runners
# -------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
