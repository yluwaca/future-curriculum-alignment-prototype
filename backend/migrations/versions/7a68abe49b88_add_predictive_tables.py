"""
add_predictive_tables

Revision ID: 7a68abe49b88
Revises: 489fa7376dcb
Create Date: 2026-05-25 21:32:22.910659
"""

from typing import Sequence
from typing import Union

from alembic import context
from alembic import op

import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# =========================================================
# Revision identifiers
# =========================================================

revision: str = "7a68abe49b88"

down_revision: Union[str, Sequence[str], None] = "489fa7376dcb"

branch_labels: Union[str, Sequence[str], None] = None

depends_on: Union[str, Sequence[str], None] = None


# =========================================================
# Helper Functions
# =========================================================

def is_offline_mode() -> bool:
    """
    Determine whether Alembic is running
    in offline (--sql) mode.
    """

    return context.is_offline_mode()


def index_exists(index_name: str) -> bool:
    """
    Check if PostgreSQL index exists.

    Offline mode cannot query the database,
    so we safely return False to emit SQL.
    """

    if is_offline_mode():
        return False

    connection = op.get_bind()

    query = sa.text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_indexes
            WHERE indexname = :index_name
        )
        """
    )

    result = connection.execute(
        query,
        {"index_name": index_name},
    )

    return bool(result.scalar())


def constraint_exists(
    table_name: str,
    constraint_name: str,
) -> bool:
    """
    Check if PostgreSQL constraint exists.

    Offline mode cannot query the database,
    so we safely return False.
    """

    if is_offline_mode():
        return False

    connection = op.get_bind()

    query = sa.text(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints
            WHERE table_name = :table_name
            AND constraint_name = :constraint_name
        )
        """
    )

    result = connection.execute(
        query,
        {
            "table_name": table_name,
            "constraint_name": constraint_name,
        },
    )

    return bool(result.scalar())


# =========================================================
# Upgrade
# =========================================================

def upgrade() -> None:
    """
    Upgrade predictive modelling schema.
    """

    # =====================================================
    # CURRICULUM MODULE
    # =====================================================

    op.alter_column(
        "curriculum_module",
        "programme",
        existing_type=sa.VARCHAR(length=100),
        type_=sa.String(length=150),
        existing_nullable=True,
    )

    op.alter_column(
        "curriculum_module",
        "nqf_level",
        existing_type=sa.INTEGER(),
        nullable=True,
    )

    op.alter_column(
        "curriculum_module",
        "faculty",
        existing_type=sa.VARCHAR(length=100),
        nullable=True,
    )

    curriculum_indexes = [
        (
            "idx_curriculummodule_active_code",
            ["is_active", "module_code"],
        ),
        (
            "idx_curriculummodule_faculty_nqf",
            ["faculty", "nqf_level"],
        ),
        (
            "idx_curriculummodule_programme",
            ["programme"],
        ),
    ]

    for index_name, columns in curriculum_indexes:

        if not index_exists(index_name):

            op.create_index(
                index_name,
                "curriculum_module",
                columns,
                unique=False,
            )

    # =====================================================
    # JOB POSTING
    # =====================================================

    # IMPORTANT:
    # Preserve UUID posting_id
    # DO NOT replace with integer IDs

    op.alter_column(
        "job_posting",
        "posted_date",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
    )

    op.alter_column(
        "job_posting",
        "posting_quarter",
        existing_type=sa.INTEGER(),
        nullable=False,
    )

    job_indexes = [
        (
            "idx_jobposting_posted_date",
            ["posted_date"],
        ),
        (
            "idx_jobposting_processed",
            ["is_processed"],
        ),
        (
            "idx_jobposting_region_month",
            ["region", "posting_month"],
        ),
        (
            "idx_jobposting_year_quarter",
            ["posting_year", "posting_quarter"],
        ),
    ]

    for index_name, columns in job_indexes:

        if not index_exists(index_name):

            op.create_index(
                index_name,
                "job_posting",
                columns,
                unique=False,
            )

    # =====================================================
    # PREDICTIVE OUTPUT
    # =====================================================

    # IMPORTANT:
    # Preserve UUID prediction_id
    # DO NOT replace with integer IDs

    op.alter_column(
        "predictive_output",
        "curriculum_nqf_level",
        existing_type=sa.INTEGER(),
        nullable=True,
    )

    op.alter_column(
        "predictive_output",
        "faculty",
        existing_type=sa.VARCHAR(length=100),
        nullable=True,
    )

    predictive_indexes = [
        (
            "idx_predictiveoutput_aligned",
            ["is_aligned"],
        ),
        (
            "idx_predictiveoutput_model_type",
            ["model_type"],
        ),
        (
            "idx_predictiveoutput_module_timestamp",
            [
                "curriculum_module_code",
                "prediction_timestamp",
            ],
        ),
    ]

    for index_name, columns in predictive_indexes:

        if not index_exists(index_name):

            op.create_index(
                index_name,
                "predictive_output",
                columns,
                unique=False,
            )

    # =====================================================
    # AUTH TOKEN HARDENING
    # =====================================================

    auth_indexes = [
        (
            "idx_authtoken_expiry",
            ["expires_at"],
        ),
        (
            "idx_authtoken_hash",
            ["token_hash"],
        ),
        (
            "idx_authtoken_subject_revoked",
            ["subject_id", "revoked"],
        ),
    ]

    for index_name, columns in auth_indexes:

        if not index_exists(index_name):

            op.create_index(
                index_name,
                "sec01_authtoken",
                columns,
                unique=False,
            )

    # -----------------------------------------------------
    # Foreign Key Hardening
    # -----------------------------------------------------

    if not constraint_exists(
        "sec01_authtoken",
        "fk_sec01_authtoken_subject_id_jus01_systemidentity",
    ):

        try:

            op.drop_constraint(
                "sec01_authtoken_subject_id_fkey",
                "sec01_authtoken",
                type_="foreignkey",
            )

        except Exception:
            pass

        op.create_foreign_key(
            "fk_sec01_authtoken_subject_id_jus01_systemidentity",
            "sec01_authtoken",
            "jus01_systemidentity",
            ["subject_id"],
            ["identity_id"],
            ondelete="CASCADE",
        )

    # =====================================================
    # ROLE INDEXES
    # =====================================================

    if not index_exists("idx_role_name"):

        op.create_index(
            "idx_role_name",
            "sec02_role",
            ["role_name"],
            unique=False,
        )

    if not constraint_exists(
        "sec02_role",
        "uq_sec02_role_role_name",
    ):

        op.create_unique_constraint(
            "uq_sec02_role_role_name",
            "sec02_role",
            ["role_name"],
        )

    # =====================================================
    # PERMISSION INDEXES
    # =====================================================

    if not index_exists("idx_permission_name"):

        op.create_index(
            "idx_permission_name",
            "sec03_permission",
            ["permission_name"],
            unique=False,
        )

    if not constraint_exists(
        "sec03_permission",
        "uq_sec03_permission_permission_name",
    ):

        op.create_unique_constraint(
            "uq_sec03_permission_permission_name",
            "sec03_permission",
            ["permission_name"],
        )


# =========================================================
# Downgrade
# =========================================================

def downgrade() -> None:
    """
    Downgrade predictive modelling schema.
    """

    indexes_to_drop = [
        (
            "predictive_output",
            "idx_predictiveoutput_module_timestamp",
        ),
        (
            "predictive_output",
            "idx_predictiveoutput_model_type",
        ),
        (
            "predictive_output",
            "idx_predictiveoutput_aligned",
        ),
        (
            "job_posting",
            "idx_jobposting_year_quarter",
        ),
        (
            "job_posting",
            "idx_jobposting_region_month",
        ),
        (
            "job_posting",
            "idx_jobposting_processed",
        ),
        (
            "job_posting",
            "idx_jobposting_posted_date",
        ),
        (
            "curriculum_module",
            "idx_curriculummodule_programme",
        ),
        (
            "curriculum_module",
            "idx_curriculummodule_faculty_nqf",
        ),
        (
            "curriculum_module",
            "idx_curriculummodule_active_code",
        ),
        (
            "sec01_authtoken",
            "idx_authtoken_expiry",
        ),
        (
            "sec01_authtoken",
            "idx_authtoken_hash",
        ),
        (
            "sec01_authtoken",
            "idx_authtoken_subject_revoked",
        ),
        (
            "sec02_role",
            "idx_role_name",
        ),
        (
            "sec03_permission",
            "idx_permission_name",
        ),
    ]

    for table_name, index_name in indexes_to_drop:

        if not is_offline_mode():

            if index_exists(index_name):

                op.drop_index(
                    index_name,
                    table_name=table_name,
                )

    # =====================================================
    # Restore nullable state
    # =====================================================

    op.alter_column(
        "job_posting",
        "posted_date",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
    )

    op.alter_column(
        "job_posting",
        "posting_quarter",
        existing_type=sa.INTEGER(),
        nullable=True,
    )

    op.alter_column(
        "predictive_output",
        "curriculum_nqf_level",
        existing_type=sa.INTEGER(),
        nullable=False,
    )

    op.alter_column(
        "predictive_output",
        "faculty",
        existing_type=sa.VARCHAR(length=100),
        nullable=False,
    )

    op.alter_column(
        "curriculum_module",
        "programme",
        existing_type=sa.String(length=150),
        type_=sa.VARCHAR(length=100),
        existing_nullable=True,
    )

    op.alter_column(
        "curriculum_module",
        "nqf_level",
        existing_type=sa.INTEGER(),
        nullable=False,
    )

    op.alter_column(
        "curriculum_module",
        "faculty",
        existing_type=sa.VARCHAR(length=100),
        nullable=False,
    )

    # =====================================================
    # Remove FK
    # =====================================================

    if not is_offline_mode():

        if constraint_exists(
            "sec01_authtoken",
            "fk_sec01_authtoken_subject_id_jus01_systemidentity",
        ):

            op.drop_constraint(
                "fk_sec01_authtoken_subject_id_jus01_systemidentity",
                "sec01_authtoken",
                type_="foreignkey",
            )