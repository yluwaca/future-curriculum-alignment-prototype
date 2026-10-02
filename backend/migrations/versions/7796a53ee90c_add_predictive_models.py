"""add_predictive_models

Revision ID: 7796a53ee90c
Revises: 7efe7bde1ffb
Create Date: 2026-05-24 18:29:16.311217

This migration adds the core predictive modelling tables required for the
curriculum-labour market alignment system:
- curriculum_module: Stores institutional curriculum data (CPUT modules)
- job_posting: Stores labour market signals (job postings with extracted skills)
- predictive_output: Stores model predictions, forecasts, and explainability data

It also enhances existing security/audit tables with additional indexes and
constraints to support the predictive pipeline's auditability requirements.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision: str = '7796a53ee90c'
down_revision: Union[str, Sequence[str], None] = '7efe7bde1ffb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: Create predictive modelling tables and enhance audit indexes."""
    
    # =========================================================================
    # TABLE: curriculum_module
    # =========================================================================
    op.create_table(
        'curriculum_module',
        sa.Column('module_id', sa.UUID(), nullable=False),
        sa.Column('module_code', sa.String(length=50), nullable=False, comment='Unique module identifier (e.g., COS301T)'),
        sa.Column('module_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True, comment='Module description and learning outcomes'),
        sa.Column('nqf_level', sa.Integer(), nullable=False, comment='National Qualifications Framework level (6-8)'),
        sa.Column('faculty', sa.String(length=100), nullable=False, comment='Academic faculty/department'),
        sa.Column('programme', sa.String(length=100), nullable=True, comment='Degree/diploma programme name'),
        sa.Column('credits', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'), comment='Flag for currently offered modules'),
        sa.Column('data_source', sa.String(length=100), nullable=True, comment='Source system identifier'),
        sa.Column('last_processed_at', sa.DateTime(timezone=True), nullable=True, comment='Last ETL processing timestamp'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('module_id', name='pk_curriculum_module'),
        comment='Curriculum modules for predictive alignment analysis'
    )
    
    # Indexes for curriculum_module (named consistently for downgrade)
    op.create_index('ix_curriculum_active_code', 'curriculum_module', ['is_active', 'module_code'], unique=False)
    op.create_index('ix_curriculum_faculty_nqf', 'curriculum_module', ['faculty', 'nqf_level'], unique=False)
    op.create_index('ix_curriculum_faculty', 'curriculum_module', ['faculty'], unique=False)
    op.create_index('ix_curriculum_module_code', 'curriculum_module', ['module_code'], unique=True)
    op.create_index('ix_curriculum_nqf_level', 'curriculum_module', ['nqf_level'], unique=False)
    
    # =========================================================================
    # TABLE: job_posting
    # =========================================================================
    op.create_table(
        'job_posting',
        sa.Column('posting_id', sa.UUID(), nullable=False),
        sa.Column('job_id', sa.String(length=100), nullable=False, comment='External source job identifier'),
        sa.Column('job_title', sa.String(length=255), nullable=False),
        sa.Column('job_description', sa.Text(), nullable=True),
        sa.Column('required_skills', sa.Text(), nullable=True, comment='Extracted/normalised skill keywords'),
        sa.Column('education_level', sa.String(length=100), nullable=True),
        sa.Column('experience_years', sa.Integer(), nullable=True),
        sa.Column('region', sa.String(length=100), nullable=False, comment='Geographic region (e.g., Western Cape)'),
        sa.Column('country', sa.String(length=2), nullable=False, comment='ISO 3166-1 alpha-2 country code'),
        sa.Column('employment_type', sa.String(length=50), nullable=True),
        sa.Column('salary_min', sa.Float(), nullable=True),
        sa.Column('salary_max', sa.Float(), nullable=True),
        sa.Column('is_processed', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='ETL processing flag'),
        sa.Column('posting_year', sa.Integer(), nullable=False, comment='Year of job posting'),
        sa.Column('posting_month', sa.Integer(), nullable=False, comment='Month of job posting (1-12)'),
        sa.Column('posting_quarter', sa.Integer(), nullable=True, comment='Quarter of job posting (1-4)'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('posting_id', name='pk_job_posting'),
        comment='Labour market job postings for skills demand analysis'
    )
    
    # Indexes for job_posting (named consistently for downgrade)
    op.create_index('ix_job_created_at', 'job_posting', ['created_at'], unique=False)
    op.create_index('ix_job_processed', 'job_posting', ['is_processed'], unique=False)
    op.create_index('ix_job_region_month', 'job_posting', ['region', 'posting_month'], unique=False)
    op.create_index('ix_job_posting_job_id', 'job_posting', ['job_id'], unique=True)
    op.create_index('ix_job_posting_month', 'job_posting', ['posting_month'], unique=False)
    op.create_index('ix_job_posting_year', 'job_posting', ['posting_year'], unique=False)
    op.create_index('ix_job_posting_region', 'job_posting', ['region'], unique=False)
    
    # =========================================================================
    # TABLE: predictive_output
    # =========================================================================
    op.create_table(
        'predictive_output',
        sa.Column('prediction_id', sa.UUID(), nullable=False),
        sa.Column('curriculum_module_code', sa.String(length=50), nullable=False),
        sa.Column('curriculum_nqf_level', sa.Integer(), nullable=False),
        sa.Column('faculty', sa.String(length=100), nullable=False),
        sa.Column('model_type', sa.String(length=50), nullable=False, comment='XGBoost/LSTM/ensemble'),
        sa.Column('model_version', sa.String(length=50), nullable=True, comment='Semantic version string'),
        sa.Column('prediction_timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # XGBoost alignment classifier outputs
        sa.Column('alignment_score', sa.Float(), nullable=True, comment='Cosine similarity score [0,1]'),
        sa.Column('is_aligned', sa.Boolean(), nullable=True, comment='Binary classification result'),
        sa.Column('confidence_score', sa.Float(), nullable=True, comment='Model confidence/probability'),
        sa.Column('gap_score', sa.Float(), nullable=True, comment='Quantified curriculum-labour gap'),
        sa.Column('gap_flag', sa.Boolean(), nullable=False, server_default=sa.text('false'), comment='Critical gap indicator'),
        
        # LSTM forecasting outputs
        sa.Column('forecast_horizon_months', sa.Integer(), nullable=True, comment='Forecast look-ahead period'),
        sa.Column('forecast_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Time-series forecast payload'),
        sa.Column('forecast_rmse', sa.Float(), nullable=True, comment='Forecast error metric'),
        sa.Column('forecast_mape', sa.Float(), nullable=True, comment='Mean absolute percentage error'),
        
        # Explainability artifacts (SHAP/LIME)
        sa.Column('shap_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Aggregated SHAP values'),
        sa.Column('shap_full_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Complete SHAP output'),
        sa.Column('top_influencing_skills', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Top-k skill contributors'),
        
        # Context and audit metadata
        sa.Column('data_region', sa.String(length=100), nullable=True),
        sa.Column('input_features_hash', sa.String(length=64), nullable=True, comment='SHA-256 of input feature vector'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('prediction_id', name='pk_predictive_output'),
        comment='Predictive model outputs with explainability and audit metadata'
    )
    
    # Indexes for predictive_output (named consistently for downgrade)
    op.create_index('ix_pred_aligned', 'predictive_output', ['is_aligned'], unique=False)
    op.create_index('ix_pred_model_type', 'predictive_output', ['model_type'], unique=False)
    op.create_index('ix_pred_module_ts', 'predictive_output', ['curriculum_module_code', 'prediction_timestamp'], unique=False)
    op.create_index('ix_pred_module_code', 'predictive_output', ['curriculum_module_code'], unique=False)
    op.create_index('ix_pred_timestamp', 'predictive_output', ['prediction_timestamp'], unique=False)
    
    # =========================================================================
    # ENHANCEMENTS: Existing audit/security tables
    # =========================================================================
    
    # -------------------------------------------------------------------------
    # dsl01_auditevent: Strengthen audit trail
    # -------------------------------------------------------------------------
    op.alter_column(
        'dsl01_auditevent', 'event_time',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text('now()')
    )
    op.create_index('ix_audit_actor', 'dsl01_auditevent', ['actor_id'], unique=False)
    op.create_index('ix_audit_actor_time', 'dsl01_auditevent', ['actor_id', 'event_time'], unique=False)
    op.create_index('ix_audit_event_time', 'dsl01_auditevent', ['event_time'], unique=False)
    op.create_index('ix_audit_result', 'dsl01_auditevent', ['result'], unique=False)
    op.create_index('ix_audit_token', 'dsl01_auditevent', ['token_id'], unique=False)
    op.create_index('ix_audit_type', 'dsl01_auditevent', ['event_type'], unique=False)
    
    # Add FK with validation-safe approach (PostgreSQL 12+)
    op.create_foreign_key(
        'fk_auditevent_actor_identity',
        'dsl01_auditevent', 'jus01_systemidentity',
        ['actor_id'], ['identity_id'],
        ondelete='SET NULL'
    )
    
    # -------------------------------------------------------------------------
    # jus01_systemidentity: Optimise identity lookups
    # FIX: Populate NULL values BEFORE setting NOT NULL constraint
    # -------------------------------------------------------------------------
    
    # Step 1: Backfill any existing NULL identity_type values with default 'system'
    op.execute("""
        UPDATE jus01_systemidentity 
        SET identity_type = 'system' 
        WHERE identity_type IS NULL
    """)
    
    # Step 2: Now safely set the column to NOT NULL
    op.alter_column(
        'jus01_systemidentity', 'identity_type',
        existing_type=sa.VARCHAR(),
        nullable=False
    )
    
    # Step 3: Ensure created_at is NOT NULL with default
    op.alter_column(
        'jus01_systemidentity', 'created_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text('now()')
    )
    
    # Step 4: Add supporting indexes
    op.create_index('ix_identity_email', 'jus01_systemidentity', ['email'], unique=False)
    op.create_index('ix_identity_status', 'jus01_systemidentity', ['status'], unique=False)
    op.create_index('ix_identity_type', 'jus01_systemidentity', ['identity_type'], unique=False)
    
    # -------------------------------------------------------------------------
    # sec01_authtoken: Enhance token management
    # -------------------------------------------------------------------------
    op.alter_column(
        'sec01_authtoken', 'issued_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text('now()')
    )
    
    # Drop auto-generated index and replace with explicitly named constraints
    op.drop_index('ix_sec01_authtoken_token_hash', table_name='sec01_authtoken')
    op.create_index('ix_authtoken_expiry', 'sec01_authtoken', ['expires_at'], unique=False)
    op.create_index('ix_authtoken_hash', 'sec01_authtoken', ['token_hash'], unique=False)
    op.create_index('ix_authtoken_revoked', 'sec01_authtoken', ['revoked'], unique=False)
    op.create_index('ix_authtoken_subject', 'sec01_authtoken', ['subject_id'], unique=False)
    op.create_index('ix_authtoken_subject_revoked', 'sec01_authtoken', ['subject_id', 'revoked'], unique=False)
    op.create_unique_constraint('uq_authtoken_token_hash', 'sec01_authtoken', ['token_hash'])
    
    # Update planner statistics after bulk changes (optional but recommended)
    op.execute('ANALYZE curriculum_module')
    op.execute('ANALYZE job_posting')
    op.execute('ANALYZE predictive_output')


def downgrade() -> None:
    """Downgrade schema: Remove predictive modelling tables and revert audit enhancements."""
    
    # =========================================================================
    # REVERT: Existing audit/security table enhancements (reverse order)
    # =========================================================================
    
    # -------------------------------------------------------------------------
    # sec01_authtoken: Remove enhanced indexes and constraints
    # -------------------------------------------------------------------------
    op.drop_constraint('uq_authtoken_token_hash', 'sec01_authtoken', type_='unique')
    op.drop_index('ix_authtoken_subject_revoked', table_name='sec01_authtoken')
    op.drop_index('ix_authtoken_subject', table_name='sec01_authtoken')
    op.drop_index('ix_authtoken_revoked', table_name='sec01_authtoken')
    op.drop_index('ix_authtoken_hash', table_name='sec01_authtoken')
    op.drop_index('ix_authtoken_expiry', table_name='sec01_authtoken')
    # Recreate original auto-generated index
    op.create_index('ix_sec01_authtoken_token_hash', 'sec01_authtoken', ['token_hash'], unique=True)
    op.alter_column(
        'sec01_authtoken', 'issued_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text('now()')
    )
    
    # -------------------------------------------------------------------------
    # jus01_systemidentity: Remove enhanced indexes and relax constraints
    # FIX: Drop indexes first, then relax NOT NULL constraint
    # -------------------------------------------------------------------------
    op.drop_index('ix_identity_type', table_name='jus01_systemidentity')
    op.drop_index('ix_identity_status', table_name='jus01_systemidentity')
    op.drop_index('ix_identity_email', table_name='jus01_systemidentity')
    
    # Relax NOT NULL constraint (order matters: created_at first, then identity_type)
    op.alter_column(
        'jus01_systemidentity', 'created_at',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text('now()')
    )
    op.alter_column(
        'jus01_systemidentity', 'identity_type',
        existing_type=sa.VARCHAR(),
        nullable=True
    )
    
    # -------------------------------------------------------------------------
    # dsl01_auditevent: Remove enhanced indexes and foreign key
    # -------------------------------------------------------------------------
    op.drop_constraint('fk_auditevent_actor_identity', 'dsl01_auditevent', type_='foreignkey')
    op.drop_index('ix_audit_type', table_name='dsl01_auditevent')
    op.drop_index('ix_audit_token', table_name='dsl01_auditevent')
    op.drop_index('ix_audit_result', table_name='dsl01_auditevent')
    op.drop_index('ix_audit_event_time', table_name='dsl01_auditevent')
    op.drop_index('ix_audit_actor_time', table_name='dsl01_auditevent')
    op.drop_index('ix_audit_actor', table_name='dsl01_auditevent')
    op.alter_column(
        'dsl01_auditevent', 'event_time',
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text('now()')
    )
    
    # =========================================================================
    # DROP: Predictive modelling tables (reverse creation order)
    # =========================================================================
    
    # predictive_output: Drop indexes then table
    op.drop_index('ix_pred_timestamp', table_name='predictive_output')
    op.drop_index('ix_pred_module_code', table_name='predictive_output')
    op.drop_index('ix_pred_module_ts', table_name='predictive_output')
    op.drop_index('ix_pred_model_type', table_name='predictive_output')
    op.drop_index('ix_pred_aligned', table_name='predictive_output')
    op.drop_table('predictive_output')
    
    # job_posting: Drop indexes then table
    op.drop_index('ix_job_posting_region', table_name='job_posting')
    op.drop_index('ix_job_posting_year', table_name='job_posting')
    op.drop_index('ix_job_posting_month', table_name='job_posting')
    op.drop_index('ix_job_posting_job_id', table_name='job_posting')
    op.drop_index('ix_job_region_month', table_name='job_posting')
    op.drop_index('ix_job_processed', table_name='job_posting')
    op.drop_index('ix_job_created_at', table_name='job_posting')
    op.drop_table('job_posting')
    
    # curriculum_module: Drop indexes then table
    op.drop_index('ix_curriculum_nqf_level', table_name='curriculum_module')
    op.drop_index('ix_curriculum_module_code', table_name='curriculum_module')
    op.drop_index('ix_curriculum_faculty', table_name='curriculum_module')
    op.drop_index('ix_curriculum_faculty_nqf', table_name='curriculum_module')
    op.drop_index('ix_curriculum_active_code', table_name='curriculum_module')
    op.drop_table('curriculum_module')