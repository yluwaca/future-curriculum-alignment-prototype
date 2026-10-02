"""Add alignment_score to curriculum_module."""
from alembic import op
import sqlalchemy as sa

revision = "add_curriculum_alignment_score"
down_revision = "perf_idx_001"

def upgrade():
    op.add_column("curriculum_module", sa.Column("alignment_score", sa.Float, nullable=True))

def downgrade():
    op.drop_column("curriculum_module", "alignment_score")
