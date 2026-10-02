"""align_current_models_v5

Revision ID: 489fa7376dcb
Revises: 7796a53ee90c
Create Date: 2026-05-25 14:01:35.338119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '489fa7376dcb'
down_revision: Union[str, Sequence[str], None] = '7796a53ee90c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # =========================================================
    # AUDIT EVENT
    # =========================================================

    op.create_index(
        "idx_audit_actor",
        "dsl01_auditevent",
        ["actor_id"],
        unique=False
    )

    op.create_index(
        "idx_audit_actor_time",
        "dsl01_auditevent",
        ["actor_id", "event_time"],
        unique=False
    )

    op.create_index(
        "idx_audit_event_time",
        "dsl01_auditevent",
        ["event_time"],
        unique=False
    )

    op.create_index(
        "idx_audit_result",
        "dsl01_auditevent",
        ["result"],
        unique=False
    )

    op.create_index(
        "idx_audit_token",
        "dsl01_auditevent",
        ["token_id"],
        unique=False
    )

    op.create_index(
        "idx_audit_type",
        "dsl01_auditevent",
        ["event_type"],
        unique=False
    )

    # =========================================================
    # JOB POSTING
    # =========================================================

    op.add_column(
        "job_posting",
        sa.Column(
            "posted_date",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "job_posting",
        sa.Column(
            "closed_date",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "job_posting",
        sa.Column(
            "source",
            sa.String(length=100),
            nullable=True
        )
    )

    op.add_column(
        "job_posting",
        sa.Column(
            "source_url",
            sa.String(length=1000),
            nullable=True
        )
    )

    op.add_column(
        "job_posting",
        sa.Column(
            "embedding_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false")
        )
    )

    op.add_column(
        "job_posting",
        sa.Column(
            "last_processed_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    # Convert TEXT -> JSONB safely
    op.execute("""
    ALTER TABLE job_posting
    ALTER COLUMN required_skills
    TYPE JSONB
    USING (
        CASE
            WHEN required_skills IS NULL THEN NULL
            WHEN trim(required_skills) = '' THEN NULL
            ELSE to_jsonb(required_skills)
        END
    )
    """)

    op.alter_column(
        "job_posting",
        "salary_min",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=True
    )

    op.alter_column(
        "job_posting",
        "salary_max",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=True
    )

    # =========================================================
    # SYSTEM IDENTITY
    # =========================================================

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "is_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false")
        )
    )

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0")
        )
    )

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    op.add_column(
        "jus01_systemidentity",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    # =========================================================
    # PREDICTIVE OUTPUT
    # =========================================================

    op.add_column(
        "predictive_output",
        sa.Column(
            "inference_duration_ms",
            sa.Integer(),
            nullable=True
        )
    )

    op.add_column(
        "predictive_output",
        sa.Column(
            "dataset_version",
            sa.String(length=100),
            nullable=True
        )
    )

    op.alter_column(
        "predictive_output",
        "alignment_score",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=True
    )

    op.alter_column(
        "predictive_output",
        "confidence_score",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=True
    )

    op.alter_column(
        "predictive_output",
        "gap_score",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=True
    )

    op.alter_column(
        "predictive_output",
        "forecast_rmse",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=True
    )

    op.alter_column(
        "predictive_output",
        "forecast_mape",
        existing_type=sa.DOUBLE_PRECISION(precision=53),
        type_=sa.Numeric(precision=10, scale=4),
        existing_nullable=True
    )

    # =========================================================
    # AUTH TOKEN
    # =========================================================

    op.add_column(
        "sec01_authtoken",
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "sec01_authtoken",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True
        )
    )

    op.add_column(
        "sec01_authtoken",
        sa.Column(
            "device_name",
            sa.String(length=255),
            nullable=True
        )
    )

    op.add_column(
        "sec01_authtoken",
        sa.Column(
            "ip_address",
            sa.String(length=100),
            nullable=True
        )
    )

    op.add_column(
        "sec01_authtoken",
        sa.Column(
            "user_agent",
            sa.String(length=1000),
            nullable=True
        )
    )

    # =========================================================
    # ROLE
    # =========================================================

    op.add_column(
        "sec02_role",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    op.add_column(
        "sec02_role",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    # =========================================================
    # PERMISSION
    # =========================================================

    op.add_column(
        "sec03_permission",
        sa.Column(
            "permission_name",
            sa.String(length=150),
            nullable=True
        )
    )

    op.add_column(
        "sec03_permission",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    op.add_column(
        "sec03_permission",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    # =========================================================
    # ROLE PERMISSION
    # =========================================================

    op.add_column(
        "sec04_rolepermission",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    op.add_column(
        "sec04_rolepermission",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    # =========================================================
    # USER ROLE
    # =========================================================

    op.add_column(
        "sec05_userrole",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

    op.add_column(
        "sec05_userrole",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False
        )
    )

def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(op.f('fk_sec05_userrole_identity_id_jus01_systemidentity'), 'sec05_userrole', type_='foreignkey')
    op.drop_constraint(op.f('fk_sec05_userrole_role_id_sec02_role'), 'sec05_userrole', type_='foreignkey')
    op.create_foreign_key('sec05_userrole_role_id_fkey', 'sec05_userrole', 'sec02_role', ['role_id'], ['role_id'])
    op.create_foreign_key('sec05_userrole_identity_id_fkey', 'sec05_userrole', 'jus01_systemidentity', ['identity_id'], ['identity_id'])
    op.drop_index('idx_identityrole_role', table_name='sec05_userrole')
    op.drop_index('idx_identityrole_identity', table_name='sec05_userrole')
    op.drop_column('sec05_userrole', 'updated_at')
    op.drop_column('sec05_userrole', 'created_at')
    op.drop_constraint(op.f('fk_sec04_rolepermission_permission_id_sec03_permission'), 'sec04_rolepermission', type_='foreignkey')
    op.drop_constraint(op.f('fk_sec04_rolepermission_role_id_sec02_role'), 'sec04_rolepermission', type_='foreignkey')
    op.create_foreign_key('sec04_rolepermission_role_id_fkey', 'sec04_rolepermission', 'sec02_role', ['role_id'], ['role_id'])
    op.create_foreign_key('sec04_rolepermission_permission_id_fkey', 'sec04_rolepermission', 'sec03_permission', ['permission_id'], ['permission_id'])
    op.drop_index('idx_rolepermission_role', table_name='sec04_rolepermission')
    op.drop_index('idx_rolepermission_permission', table_name='sec04_rolepermission')
    op.drop_column('sec04_rolepermission', 'updated_at')
    op.drop_column('sec04_rolepermission', 'created_at')
    op.drop_constraint(op.f('uq_sec03_permission_permission_name'), 'sec03_permission', type_='unique')
    op.drop_index('idx_permission_name', table_name='sec03_permission')
    op.drop_column('sec03_permission', 'updated_at')
    op.drop_column('sec03_permission', 'created_at')
    op.drop_column('sec03_permission', 'permission_name')
    op.drop_constraint(op.f('uq_sec02_role_role_name'), 'sec02_role', type_='unique')
    op.drop_index('idx_role_name', table_name='sec02_role')
    op.drop_column('sec02_role', 'updated_at')
    op.drop_column('sec02_role', 'created_at')
    op.drop_constraint(op.f('fk_sec01_authtoken_subject_id_jus01_systemidentity'), 'sec01_authtoken', type_='foreignkey')
    op.create_foreign_key('sec01_authtoken_subject_id_fkey', 'sec01_authtoken', 'jus01_systemidentity', ['subject_id'], ['identity_id'])
    op.drop_constraint(op.f('uq_sec01_authtoken_token_hash'), 'sec01_authtoken', type_='unique')
    op.drop_index('idx_authtoken_subject_revoked', table_name='sec01_authtoken')
    op.drop_index('idx_authtoken_subject', table_name='sec01_authtoken')
    op.drop_index('idx_authtoken_revoked', table_name='sec01_authtoken')
    op.drop_index('idx_authtoken_last_used', table_name='sec01_authtoken')
    op.drop_index('idx_authtoken_hash', table_name='sec01_authtoken')
    op.drop_index('idx_authtoken_expiry', table_name='sec01_authtoken')
    op.create_unique_constraint('uq_authtoken_token_hash', 'sec01_authtoken', ['token_hash'])
    op.create_index('ix_authtoken_subject_revoked', 'sec01_authtoken', ['subject_id', 'revoked'], unique=False)
    op.create_index('ix_authtoken_subject', 'sec01_authtoken', ['subject_id'], unique=False)
    op.create_index('ix_authtoken_revoked', 'sec01_authtoken', ['revoked'], unique=False)
    op.create_index('ix_authtoken_hash', 'sec01_authtoken', ['token_hash'], unique=False)
    op.create_index('ix_authtoken_expiry', 'sec01_authtoken', ['expires_at'], unique=False)
    op.alter_column('sec01_authtoken', 'metadata',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=True)
    op.drop_column('sec01_authtoken', 'user_agent')
    op.drop_column('sec01_authtoken', 'ip_address')
    op.drop_column('sec01_authtoken', 'device_name')
    op.drop_column('sec01_authtoken', 'revoked_at')
    op.drop_column('sec01_authtoken', 'last_used_at')
    op.add_column('predictive_output', sa.Column('prediction_id', sa.UUID(), autoincrement=False, nullable=False))
    op.create_table_comment(
        'predictive_output',
        'Predictive model outputs with explainability and audit metadata',
        existing_comment=None,
        schema=None
    )
    op.drop_index(op.f('ix_predictive_output_prediction_timestamp'), table_name='predictive_output')
    op.drop_index(op.f('ix_predictive_output_curriculum_module_code'), table_name='predictive_output')
    op.drop_index('idx_predictiveoutput_module_timestamp', table_name='predictive_output')
    op.drop_index('idx_predictiveoutput_model_type', table_name='predictive_output')
    op.drop_index('idx_predictiveoutput_aligned', table_name='predictive_output')
    op.create_index('ix_pred_timestamp', 'predictive_output', ['prediction_timestamp'], unique=False)
    op.create_index('ix_pred_module_ts', 'predictive_output', ['curriculum_module_code', 'prediction_timestamp'], unique=False)
    op.create_index('ix_pred_module_code', 'predictive_output', ['curriculum_module_code'], unique=False)
    op.create_index('ix_pred_model_type', 'predictive_output', ['model_type'], unique=False)
    op.create_index('ix_pred_aligned', 'predictive_output', ['is_aligned'], unique=False)
    op.alter_column('predictive_output', 'input_features_hash',
               existing_type=sa.VARCHAR(length=64),
               comment='SHA-256 of input feature vector',
               existing_nullable=True)
    op.alter_column('predictive_output', 'top_influencing_skills',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment='Top-k skill contributors',
               existing_nullable=True)
    op.alter_column('predictive_output', 'shap_full_values',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment='Complete SHAP output',
               existing_nullable=True)
    op.alter_column('predictive_output', 'shap_summary',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment='Aggregated SHAP values',
               existing_nullable=True)
    op.alter_column('predictive_output', 'forecast_mape',
               existing_type=sa.Numeric(precision=10, scale=4),
               type_=sa.DOUBLE_PRECISION(precision=53),
               comment='Mean absolute percentage error',
               existing_nullable=True)
    op.alter_column('predictive_output', 'forecast_rmse',
               existing_type=sa.Numeric(precision=10, scale=4),
               type_=sa.DOUBLE_PRECISION(precision=53),
               comment='Forecast error metric',
               existing_nullable=True)
    op.alter_column('predictive_output', 'forecast_data',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               comment='Time-series forecast payload',
               existing_nullable=True)
    op.alter_column('predictive_output', 'forecast_horizon_months',
               existing_type=sa.INTEGER(),
               comment='Forecast look-ahead period',
               existing_nullable=True)
    op.alter_column('predictive_output', 'gap_flag',
               existing_type=sa.BOOLEAN(),
               comment='Critical gap indicator',
               existing_nullable=False,
               existing_server_default=sa.text('false'))
    op.alter_column('predictive_output', 'gap_score',
               existing_type=sa.Numeric(precision=10, scale=4),
               type_=sa.DOUBLE_PRECISION(precision=53),
               comment='Quantified curriculum-labour gap',
               existing_nullable=True)
    op.alter_column('predictive_output', 'confidence_score',
               existing_type=sa.Numeric(precision=10, scale=4),
               type_=sa.DOUBLE_PRECISION(precision=53),
               comment='Model confidence/probability',
               existing_nullable=True)
    op.alter_column('predictive_output', 'is_aligned',
               existing_type=sa.BOOLEAN(),
               comment='Binary classification result',
               existing_nullable=True)
    op.alter_column('predictive_output', 'alignment_score',
               existing_type=sa.Numeric(precision=10, scale=4),
               type_=sa.DOUBLE_PRECISION(precision=53),
               comment='Cosine similarity score [0,1]',
               existing_nullable=True)
    op.alter_column('predictive_output', 'model_version',
               existing_type=sa.VARCHAR(length=50),
               comment='Semantic version string',
               existing_nullable=True)
    op.alter_column('predictive_output', 'model_type',
               existing_type=sa.VARCHAR(length=50),
               comment='XGBoost/LSTM/ensemble',
               existing_nullable=False)
    op.alter_column('predictive_output', 'faculty',
               existing_type=sa.VARCHAR(length=100),
               nullable=False)
    op.alter_column('predictive_output', 'curriculum_nqf_level',
               existing_type=sa.INTEGER(),
               nullable=False)
    op.drop_column('predictive_output', 'dataset_version')
    op.drop_column('predictive_output', 'inference_duration_ms')
    op.drop_column('predictive_output', 'id')
    op.drop_index(op.f('ix_jus01_systemidentity_email'), table_name='jus01_systemidentity')
    op.drop_index('idx_identity_type', table_name='jus01_systemidentity')
    op.drop_index('idx_identity_status', table_name='jus01_systemidentity')
    op.drop_index('idx_identity_email', table_name='jus01_systemidentity')
    op.drop_index('idx_identity_active', table_name='jus01_systemidentity')
    op.create_unique_constraint('jus01_systemidentity_email_key', 'jus01_systemidentity', ['email'])
    op.create_index('ix_identity_type', 'jus01_systemidentity', ['identity_type'], unique=False)
    op.create_index('ix_identity_status', 'jus01_systemidentity', ['status'], unique=False)
    op.create_index('ix_identity_email', 'jus01_systemidentity', ['email'], unique=False)
    op.alter_column('jus01_systemidentity', 'status',
               existing_type=sa.VARCHAR(),
               nullable=True)
    op.drop_column('jus01_systemidentity', 'deleted_at')
    op.drop_column('jus01_systemidentity', 'updated_at')
    op.drop_column('jus01_systemidentity', 'locked_until')
    op.drop_column('jus01_systemidentity', 'last_login_at')
    op.drop_column('jus01_systemidentity', 'failed_login_attempts')
    op.drop_column('jus01_systemidentity', 'is_admin')
    op.add_column('job_posting', sa.Column('posting_id', sa.UUID(), autoincrement=False, nullable=False))
    op.create_table_comment(
        'job_posting',
        'Labour market job postings for skills demand analysis',
        existing_comment=None,
        schema=None
    )
    op.drop_index(op.f('ix_job_posting_posted_date'), table_name='job_posting')
    op.drop_index('idx_jobposting_year_quarter', table_name='job_posting')
    op.drop_index('idx_jobposting_region_month', table_name='job_posting')
    op.drop_index('idx_jobposting_processed', table_name='job_posting')
    op.drop_index('idx_jobposting_posted_date', table_name='job_posting')
    op.create_index('ix_job_region_month', 'job_posting', ['region', 'posting_month'], unique=False)
    op.create_index('ix_job_processed', 'job_posting', ['is_processed'], unique=False)
    op.create_index('ix_job_posting_year', 'job_posting', ['posting_year'], unique=False)
    op.create_index('ix_job_posting_month', 'job_posting', ['posting_month'], unique=False)
    op.create_index('ix_job_created_at', 'job_posting', ['created_at'], unique=False)
    op.alter_column('job_posting', 'is_processed',
               existing_type=sa.BOOLEAN(),
               comment='ETL processing flag',
               existing_nullable=False,
               existing_server_default=sa.text('false'))
    op.alter_column('job_posting', 'posting_quarter',
               existing_type=sa.INTEGER(),
               nullable=True,
               comment='Quarter of job posting (1-4)')
    op.alter_column('job_posting', 'posting_month',
               existing_type=sa.INTEGER(),
               comment='Month of job posting (1-12)',
               existing_nullable=False)
    op.alter_column('job_posting', 'posting_year',
               existing_type=sa.INTEGER(),
               comment='Year of job posting',
               existing_nullable=False)
    op.alter_column('job_posting', 'salary_max',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.DOUBLE_PRECISION(precision=53),
               existing_nullable=True)
    op.alter_column('job_posting', 'salary_min',
               existing_type=sa.Numeric(precision=12, scale=2),
               type_=sa.DOUBLE_PRECISION(precision=53),
               existing_nullable=True)
    op.alter_column('job_posting', 'country',
               existing_type=sa.VARCHAR(length=2),
               comment='ISO 3166-1 alpha-2 country code',
               existing_nullable=False)
    op.alter_column('job_posting', 'region',
               existing_type=sa.VARCHAR(length=100),
               comment='Geographic region (e.g., Western Cape)',
               existing_nullable=False)
    op.alter_column('job_posting', 'required_skills',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               type_=sa.TEXT(),
               comment='Extracted/normalised skill keywords',
               existing_nullable=True)
    op.alter_column('job_posting', 'job_id',
               existing_type=sa.VARCHAR(length=100),
               comment='External source job identifier',
               existing_nullable=False)
    op.drop_column('job_posting', 'last_processed_at')
    op.drop_column('job_posting', 'embedding_generated')
    op.drop_column('job_posting', 'source_url')
    op.drop_column('job_posting', 'source')
    op.drop_column('job_posting', 'closed_date')
    op.drop_column('job_posting', 'posted_date')
    op.drop_column('job_posting', 'id')
    op.drop_index('idx_audit_type', table_name='dsl01_auditevent')
    op.drop_index('idx_audit_token', table_name='dsl01_auditevent')
    op.drop_index('idx_audit_result', table_name='dsl01_auditevent')
    op.drop_index('idx_audit_event_time', table_name='dsl01_auditevent')
    op.drop_index('idx_audit_actor_time', table_name='dsl01_auditevent')
    op.drop_index('idx_audit_actor', table_name='dsl01_auditevent')
    op.create_index('ix_audit_type', 'dsl01_auditevent', ['event_type'], unique=False)
    op.create_index('ix_audit_token', 'dsl01_auditevent', ['token_id'], unique=False)
    op.create_index('ix_audit_result', 'dsl01_auditevent', ['result'], unique=False)
    op.create_index('ix_audit_event_time', 'dsl01_auditevent', ['event_time'], unique=False)
    op.create_index('ix_audit_actor_time', 'dsl01_auditevent', ['actor_id', 'event_time'], unique=False)
    op.create_index('ix_audit_actor', 'dsl01_auditevent', ['actor_id'], unique=False)
    op.alter_column('dsl01_auditevent', 'metadata',
               existing_type=postgresql.JSONB(astext_type=sa.Text()),
               nullable=True)
    op.create_table_comment(
        'curriculum_module',
        'Curriculum modules for predictive alignment analysis',
        existing_comment=None,
        schema=None
    )
    op.drop_index(op.f('ix_curriculum_module_programme'), table_name='curriculum_module')
    op.drop_index(op.f('ix_curriculum_module_nqf_level'), table_name='curriculum_module')
    op.drop_index(op.f('ix_curriculum_module_module_code'), table_name='curriculum_module')
    op.drop_index(op.f('ix_curriculum_module_faculty'), table_name='curriculum_module')
    op.drop_index('idx_curriculummodule_programme', table_name='curriculum_module')
    op.drop_index('idx_curriculummodule_faculty_nqf', table_name='curriculum_module')
    op.drop_index('idx_curriculummodule_active_code', table_name='curriculum_module')
    op.create_index('ix_curriculum_nqf_level', 'curriculum_module', ['nqf_level'], unique=False)
    op.create_index('ix_curriculum_module_code', 'curriculum_module', ['module_code'], unique=False)
    op.create_index('ix_curriculum_faculty_nqf', 'curriculum_module', ['faculty', 'nqf_level'], unique=False)
    op.create_index('ix_curriculum_faculty', 'curriculum_module', ['faculty'], unique=False)
    op.create_index('ix_curriculum_active_code', 'curriculum_module', ['is_active', 'module_code'], unique=False)
    op.alter_column('curriculum_module', 'last_processed_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               comment='Last ETL processing timestamp',
               existing_nullable=True)
    op.alter_column('curriculum_module', 'data_source',
               existing_type=sa.VARCHAR(length=100),
               comment='Source system identifier',
               existing_nullable=True)
    op.alter_column('curriculum_module', 'is_active',
               existing_type=sa.BOOLEAN(),
               comment='Flag for currently offered modules',
               existing_nullable=False,
               existing_server_default=sa.text('true'))
    op.alter_column('curriculum_module', 'programme',
               existing_type=sa.String(length=150),
               type_=sa.VARCHAR(length=100),
               comment='Degree/diploma programme name',
               existing_nullable=True)
    op.alter_column('curriculum_module', 'faculty',
               existing_type=sa.VARCHAR(length=100),
               nullable=False,
               comment='Academic faculty/department')
    op.alter_column('curriculum_module', 'nqf_level',
               existing_type=sa.INTEGER(),
               nullable=False,
               comment='National Qualifications Framework level (6-8)')
    op.alter_column('curriculum_module', 'description',
               existing_type=sa.TEXT(),
               comment='Module description and learning outcomes',
               existing_nullable=True)
    op.alter_column('curriculum_module', 'module_code',
               existing_type=sa.VARCHAR(length=50),
               comment='Unique module identifier (e.g., COS301T)',
               existing_nullable=False)
    # ### end Alembic commands ###
