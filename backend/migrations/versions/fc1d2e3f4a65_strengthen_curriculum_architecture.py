"""strengthen curriculum architecture

Revision ID: fc1d2e3f4a65
Revises: fb9c8d7e6a53
Create Date: 2026-06-17 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "fc1d2e3f4a65"
down_revision: Union[str, Sequence[str], None] = "fb9c8d7e6a53"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "academic_faculty",
        sa.Column("faculty_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("faculty_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("faculty_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("faculty_id"),
        sa.UniqueConstraint("faculty_key"),
    )
    op.create_index(op.f("ix_academic_faculty_faculty_key"), "academic_faculty", ["faculty_key"], unique=True)
    op.create_index(op.f("ix_academic_faculty_name"), "academic_faculty", ["name"], unique=False)
    op.create_index(op.f("ix_academic_faculty_status"), "academic_faculty", ["status"], unique=False)
    op.create_index("idx_academic_faculty_status_name", "academic_faculty", ["status", "name"], unique=False)

    op.create_table(
        "academic_department",
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("faculty_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("department_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["faculty_id"], ["academic_faculty.faculty_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("department_id"),
        sa.UniqueConstraint("department_key"),
    )
    op.create_index(op.f("ix_academic_department_department_key"), "academic_department", ["department_key"], unique=True)
    op.create_index(op.f("ix_academic_department_faculty_id"), "academic_department", ["faculty_id"], unique=False)
    op.create_index(op.f("ix_academic_department_name"), "academic_department", ["name"], unique=False)
    op.create_index(op.f("ix_academic_department_status"), "academic_department", ["status"], unique=False)
    op.create_index("idx_academic_department_faculty_status", "academic_department", ["faculty_id", "status"], unique=False)

    op.create_table(
        "academic_programme",
        sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("programme_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("qualification_type", sa.String(length=100), nullable=True),
        sa.Column("nqf_level", sa.String(length=50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("programme_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["academic_department.department_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("programme_id"),
        sa.UniqueConstraint("programme_key"),
    )
    op.create_index(op.f("ix_academic_programme_programme_key"), "academic_programme", ["programme_key"], unique=True)
    op.create_index(op.f("ix_academic_programme_department_id"), "academic_programme", ["department_id"], unique=False)
    op.create_index(op.f("ix_academic_programme_name"), "academic_programme", ["name"], unique=False)
    op.create_index(op.f("ix_academic_programme_qualification_type"), "academic_programme", ["qualification_type"], unique=False)
    op.create_index(op.f("ix_academic_programme_nqf_level"), "academic_programme", ["nqf_level"], unique=False)
    op.create_index(op.f("ix_academic_programme_status"), "academic_programme", ["status"], unique=False)
    op.create_index("idx_academic_programme_department_status", "academic_programme", ["department_id", "status"], unique=False)

    op.add_column("curriculum_document", sa.Column("faculty_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("curriculum_document", sa.Column("department_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("curriculum_document", sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_curriculum_document_faculty_id", "curriculum_document", "academic_faculty", ["faculty_id"], ["faculty_id"], ondelete="SET NULL")
    op.create_foreign_key("fk_curriculum_document_department_id", "curriculum_document", "academic_department", ["department_id"], ["department_id"], ondelete="SET NULL")
    op.create_foreign_key("fk_curriculum_document_programme_id", "curriculum_document", "academic_programme", ["programme_id"], ["programme_id"], ondelete="SET NULL")
    op.create_index(op.f("ix_curriculum_document_faculty_id"), "curriculum_document", ["faculty_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_department_id"), "curriculum_document", ["department_id"], unique=False)
    op.create_index(op.f("ix_curriculum_document_programme_id"), "curriculum_document", ["programme_id"], unique=False)

    op.add_column("curriculum_module", sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_curriculum_module_programme_id", "curriculum_module", "academic_programme", ["programme_id"], ["programme_id"], ondelete="SET NULL")
    op.create_index(op.f("ix_curriculum_module_programme_id"), "curriculum_module", ["programme_id"], unique=False)

    op.add_column("document_chunk", sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("document_chunk", sa.Column("programme_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_document_chunk_module_id", "document_chunk", "curriculum_module", ["module_id"], ["module_id"], ondelete="SET NULL")
    op.create_foreign_key("fk_document_chunk_programme_id", "document_chunk", "academic_programme", ["programme_id"], ["programme_id"], ondelete="SET NULL")
    op.create_index(op.f("ix_document_chunk_module_id"), "document_chunk", ["module_id"], unique=False)
    op.create_index(op.f("ix_document_chunk_programme_id"), "document_chunk", ["programme_id"], unique=False)
    op.create_index("idx_document_chunk_programme_module", "document_chunk", ["programme_id", "module_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_document_chunk_programme_module", table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_programme_id"), table_name="document_chunk")
    op.drop_index(op.f("ix_document_chunk_module_id"), table_name="document_chunk")
    op.drop_constraint("fk_document_chunk_programme_id", "document_chunk", type_="foreignkey")
    op.drop_constraint("fk_document_chunk_module_id", "document_chunk", type_="foreignkey")
    op.drop_column("document_chunk", "programme_id")
    op.drop_column("document_chunk", "module_id")
    op.drop_index(op.f("ix_curriculum_module_programme_id"), table_name="curriculum_module")
    op.drop_constraint("fk_curriculum_module_programme_id", "curriculum_module", type_="foreignkey")
    op.drop_column("curriculum_module", "programme_id")
    op.drop_index(op.f("ix_curriculum_document_programme_id"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_department_id"), table_name="curriculum_document")
    op.drop_index(op.f("ix_curriculum_document_faculty_id"), table_name="curriculum_document")
    op.drop_constraint("fk_curriculum_document_programme_id", "curriculum_document", type_="foreignkey")
    op.drop_constraint("fk_curriculum_document_department_id", "curriculum_document", type_="foreignkey")
    op.drop_constraint("fk_curriculum_document_faculty_id", "curriculum_document", type_="foreignkey")
    op.drop_column("curriculum_document", "programme_id")
    op.drop_column("curriculum_document", "department_id")
    op.drop_column("curriculum_document", "faculty_id")
    op.drop_index("idx_academic_programme_department_status", table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_status"), table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_nqf_level"), table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_qualification_type"), table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_name"), table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_department_id"), table_name="academic_programme")
    op.drop_index(op.f("ix_academic_programme_programme_key"), table_name="academic_programme")
    op.drop_table("academic_programme")
    op.drop_index("idx_academic_department_faculty_status", table_name="academic_department")
    op.drop_index(op.f("ix_academic_department_status"), table_name="academic_department")
    op.drop_index(op.f("ix_academic_department_name"), table_name="academic_department")
    op.drop_index(op.f("ix_academic_department_faculty_id"), table_name="academic_department")
    op.drop_index(op.f("ix_academic_department_department_key"), table_name="academic_department")
    op.drop_table("academic_department")
    op.drop_index("idx_academic_faculty_status_name", table_name="academic_faculty")
    op.drop_index(op.f("ix_academic_faculty_status"), table_name="academic_faculty")
    op.drop_index(op.f("ix_academic_faculty_name"), table_name="academic_faculty")
    op.drop_index(op.f("ix_academic_faculty_faculty_key"), table_name="academic_faculty")
    op.drop_table("academic_faculty")
