"""add performance indexes for slow dashboard endpoints

Revision ID: perf_idx_001
Revises: c5d6e7f80912
Create Date: 2026-07-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = 'perf_idx_001'
down_revision = 'c5d6e7f80912'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('idx_forecast_created_at', 'forecast', ['created_at'], postgresql_using='btree', postgresql_with={'fillfactor': 90})
    op.create_index('idx_forecast_method', 'forecast', ['method'], postgresql_using='btree')
    op.create_index('idx_recommendation_created_at', 'recommendation', ['created_at'], postgresql_using='btree')
    op.create_index('idx_skill_mapping_extraction_method', 'skill_mapping', ['extraction_method'], postgresql_using='btree')
    op.create_index('idx_skill_mapping_status_confidence', 'skill_mapping', ['mapping_status', 'confidence_score'], postgresql_using='btree')


def downgrade() -> None:
    op.drop_index('idx_skill_mapping_status_confidence', table_name='skill_mapping')
    op.drop_index('idx_skill_mapping_extraction_method', table_name='skill_mapping')
    op.drop_index('idx_recommendation_created_at', table_name='recommendation')
    op.drop_index('idx_forecast_method', table_name='forecast')
    op.drop_index('idx_forecast_created_at', table_name='forecast')
