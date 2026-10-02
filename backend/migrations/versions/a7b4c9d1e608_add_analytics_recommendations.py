"""add analytics recommendations

Revision ID: a7b4c9d1e608
Revises: f6a2c8d9e305
Create Date: 2026-06-16 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b4c9d1e608"
down_revision: Union[str, Sequence[str], None] = "f6a2c8d9e305"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alignment_score",
        sa.Column("alignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score_type", sa.String(length=100), nullable=False),
        sa.Column("alignment_score", sa.Float(), nullable=False),
        sa.Column("gap_score", sa.Float(), nullable=False),
        sa.Column("curriculum_skill_count", sa.Integer(), nullable=False),
        sa.Column("labour_market_skill_count", sa.Integer(), nullable=False),
        sa.Column("overlapping_skill_count", sa.Integer(), nullable=False),
        sa.Column("missing_skill_count", sa.Integer(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("score_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("alignment_id"),
    )
    op.create_index(op.f("ix_alignment_score_document_id"), "alignment_score", ["document_id"], unique=False)
    op.create_index(op.f("ix_alignment_score_version_id"), "alignment_score", ["version_id"], unique=False)
    op.create_index(op.f("ix_alignment_score_score_type"), "alignment_score", ["score_type"], unique=False)
    op.create_index(op.f("ix_alignment_score_status"), "alignment_score", ["status"], unique=False)
    op.create_index("idx_alignment_score_version_type", "alignment_score", ["version_id", "score_type"], unique=False)
    op.create_index("idx_alignment_score_score", "alignment_score", ["alignment_score"], unique=False)

    op.create_table(
        "forecast",
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("forecast_type", sa.String(length=100), nullable=False),
        sa.Column("horizon_periods", sa.Integer(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False),
        sa.Column("forecast_value", sa.Float(), nullable=False),
        sa.Column("trend_direction", sa.String(length=50), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("forecast_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("forecast_id"),
    )
    op.create_index(op.f("ix_forecast_skill_id"), "forecast", ["skill_id"], unique=False)
    op.create_index(op.f("ix_forecast_forecast_type"), "forecast", ["forecast_type"], unique=False)
    op.create_index(op.f("ix_forecast_trend_direction"), "forecast", ["trend_direction"], unique=False)
    op.create_index(op.f("ix_forecast_status"), "forecast", ["status"], unique=False)
    op.create_index("idx_forecast_skill_type", "forecast", ["skill_id", "forecast_type"], unique=False)
    op.create_index("idx_forecast_trend_confidence", "forecast", ["trend_direction", "confidence_score"], unique=False)

    op.create_table(
        "recommendation",
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("forecast_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_type", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=50), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("recommendation_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["alignment_id"], ["alignment_score.alignment_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["curriculum_document.document_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["forecast_id"], ["forecast.forecast_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["version_id"], ["curriculum_document_version.version_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("recommendation_id"),
    )
    op.create_index(op.f("ix_recommendation_alignment_id"), "recommendation", ["alignment_id"], unique=False)
    op.create_index(op.f("ix_recommendation_forecast_id"), "recommendation", ["forecast_id"], unique=False)
    op.create_index(op.f("ix_recommendation_skill_id"), "recommendation", ["skill_id"], unique=False)
    op.create_index(op.f("ix_recommendation_document_id"), "recommendation", ["document_id"], unique=False)
    op.create_index(op.f("ix_recommendation_version_id"), "recommendation", ["version_id"], unique=False)
    op.create_index(op.f("ix_recommendation_recommendation_type"), "recommendation", ["recommendation_type"], unique=False)
    op.create_index(op.f("ix_recommendation_priority"), "recommendation", ["priority"], unique=False)
    op.create_index(op.f("ix_recommendation_priority_score"), "recommendation", ["priority_score"], unique=False)
    op.create_index(op.f("ix_recommendation_status"), "recommendation", ["status"], unique=False)
    op.create_index("idx_recommendation_status_priority", "recommendation", ["status", "priority_score"], unique=False)
    op.create_index("idx_recommendation_version_status", "recommendation", ["version_id", "status"], unique=False)

    op.create_table(
        "recommendation_explanation",
        sa.Column("explanation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("explanation_type", sa.String(length=100), nullable=False),
        sa.Column("explanation_text", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.recommendation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("explanation_id"),
    )
    op.create_index(op.f("ix_recommendation_explanation_recommendation_id"), "recommendation_explanation", ["recommendation_id"], unique=False)
    op.create_index(op.f("ix_recommendation_explanation_explanation_type"), "recommendation_explanation", ["explanation_type"], unique=False)
    op.create_index("idx_recommendation_explanation_type", "recommendation_explanation", ["recommendation_id", "explanation_type"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_recommendation_explanation_type", table_name="recommendation_explanation")
    op.drop_index(op.f("ix_recommendation_explanation_explanation_type"), table_name="recommendation_explanation")
    op.drop_index(op.f("ix_recommendation_explanation_recommendation_id"), table_name="recommendation_explanation")
    op.drop_table("recommendation_explanation")
    op.drop_index("idx_recommendation_version_status", table_name="recommendation")
    op.drop_index("idx_recommendation_status_priority", table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_status"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_priority_score"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_priority"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_recommendation_type"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_version_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_document_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_skill_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_forecast_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_alignment_id"), table_name="recommendation")
    op.drop_table("recommendation")
    op.drop_index("idx_forecast_trend_confidence", table_name="forecast")
    op.drop_index("idx_forecast_skill_type", table_name="forecast")
    op.drop_index(op.f("ix_forecast_status"), table_name="forecast")
    op.drop_index(op.f("ix_forecast_trend_direction"), table_name="forecast")
    op.drop_index(op.f("ix_forecast_forecast_type"), table_name="forecast")
    op.drop_index(op.f("ix_forecast_skill_id"), table_name="forecast")
    op.drop_table("forecast")
    op.drop_index("idx_alignment_score_score", table_name="alignment_score")
    op.drop_index("idx_alignment_score_version_type", table_name="alignment_score")
    op.drop_index(op.f("ix_alignment_score_status"), table_name="alignment_score")
    op.drop_index(op.f("ix_alignment_score_score_type"), table_name="alignment_score")
    op.drop_index(op.f("ix_alignment_score_version_id"), table_name="alignment_score")
    op.drop_index(op.f("ix_alignment_score_document_id"), table_name="alignment_score")
    op.drop_table("alignment_score")
