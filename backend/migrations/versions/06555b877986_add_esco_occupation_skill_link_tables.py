"""Add ESCO occupation + skill-link tables

Revision ID: 06555b877986
Revises: a8f64e3ecf7d
Create Date: 2026-07-06 20:26:51.890536

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '06555b877986'
down_revision: Union[str, Sequence[str], None] = 'a8f64e3ecf7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('esco_occupation',
        sa.Column('esco_occupation_id', sa.UUID(), nullable=False),
        sa.Column('esco_uri', sa.String(length=1000), nullable=True),
        sa.Column('preferred_label', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('taxonomy_version', sa.String(length=50), nullable=False),
        sa.Column('occupation_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('broader_occupation_uri', sa.String(length=1000), nullable=True),
        sa.Column('top_concept', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['parent_id'], ['esco_occupation.esco_occupation_id'], name=op.f('fk_esco_occupation_parent_id_esco_occupation'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('esco_occupation_id', name=op.f('pk_esco_occupation')),
        sa.UniqueConstraint('esco_uri', name=op.f('uq_esco_occupation_esco_uri'))
    )
    op.create_index('idx_esco_occ_label', 'esco_occupation', ['preferred_label'], unique=False)
    op.create_index('idx_esco_occ_parent_id', 'esco_occupation', ['parent_id'], unique=False)
    op.create_index('idx_esco_occ_top_concept', 'esco_occupation', ['top_concept'], unique=False)
    op.create_index(op.f('ix_esco_occupation_code'), 'esco_occupation', ['code'], unique=False)
    op.create_index(op.f('ix_esco_occupation_preferred_label'), 'esco_occupation', ['preferred_label'], unique=False)
    op.create_table('esco_occupation_skill_link',
        sa.Column('link_id', sa.UUID(), nullable=False),
        sa.Column('occupation_id', sa.UUID(), nullable=False),
        sa.Column('skill_id', sa.UUID(), nullable=False),
        sa.Column('relationship_type', sa.String(length=20), nullable=False),
        sa.Column('skill_type', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['occupation_id'], ['esco_occupation.esco_occupation_id'], name=op.f('fk_esco_occupation_skill_link_occupation_id_esco_occupation'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['skill_id'], ['esco_skill.esco_skill_id'], name=op.f('fk_esco_occupation_skill_link_skill_id_esco_skill'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('link_id', name=op.f('pk_esco_occupation_skill_link'))
    )
    op.create_index('idx_esco_occ_skill_link_occ_skill', 'esco_occupation_skill_link', ['occupation_id', 'skill_id'], unique=True)
    op.create_index('idx_esco_occ_skill_link_type', 'esco_occupation_skill_link', ['relationship_type'], unique=False)
    op.create_index(op.f('ix_esco_occupation_skill_link_occupation_id'), 'esco_occupation_skill_link', ['occupation_id'], unique=False)
    op.create_index(op.f('ix_esco_occupation_skill_link_skill_id'), 'esco_occupation_skill_link', ['skill_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_esco_occupation_skill_link_skill_id'), table_name='esco_occupation_skill_link')
    op.drop_index(op.f('ix_esco_occupation_skill_link_occupation_id'), table_name='esco_occupation_skill_link')
    op.drop_index('idx_esco_occ_skill_link_type', table_name='esco_occupation_skill_link')
    op.drop_index('idx_esco_occ_skill_link_occ_skill', table_name='esco_occupation_skill_link')
    op.drop_table('esco_occupation_skill_link')
    op.drop_index(op.f('ix_esco_occupation_preferred_label'), table_name='esco_occupation')
    op.drop_index(op.f('ix_esco_occupation_code'), table_name='esco_occupation')
    op.drop_index('idx_esco_occ_top_concept', table_name='esco_occupation')
    op.drop_index('idx_esco_occ_parent_id', table_name='esco_occupation')
    op.drop_index('idx_esco_occ_label', table_name='esco_occupation')
    op.drop_table('esco_occupation')
