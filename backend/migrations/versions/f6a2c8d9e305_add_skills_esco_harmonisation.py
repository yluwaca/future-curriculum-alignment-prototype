"""add skills esco harmonisation

Revision ID: f6a2c8d9e305
Revises: e5c1a7b9d204
Create Date: 2026-06-16 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f6a2c8d9e305"
down_revision: Union[str, Sequence[str], None] = "e5c1a7b9d204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SKILLS = [
    ("00000000-0000-4000-8000-000000000401", "python", "Python", "digital"),
    ("00000000-0000-4000-8000-000000000402", "java", "Java", "digital"),
    ("00000000-0000-4000-8000-000000000403", "javascript", "JavaScript", "digital"),
    ("00000000-0000-4000-8000-000000000404", "sql", "SQL", "digital"),
    ("00000000-0000-4000-8000-000000000405", "machine-learning", "Machine learning", "digital"),
    ("00000000-0000-4000-8000-000000000406", "data-analysis", "Data analysis", "digital"),
    ("00000000-0000-4000-8000-000000000407", "statistics", "Statistics", "analytical"),
    ("00000000-0000-4000-8000-000000000408", "database-management", "Database management", "digital"),
    ("00000000-0000-4000-8000-000000000409", "software-development", "Software development", "digital"),
    ("00000000-0000-4000-8000-000000000410", "project-management", "Project management", "business"),
    ("00000000-0000-4000-8000-000000000411", "communication", "Communication", "transversal"),
    ("00000000-0000-4000-8000-000000000412", "problem-solving", "Problem solving", "transversal"),
    ("00000000-0000-4000-8000-000000000413", "research", "Research", "analytical"),
    ("00000000-0000-4000-8000-000000000414", "business-intelligence", "Business intelligence", "digital"),
    ("00000000-0000-4000-8000-000000000415", "cloud-computing", "Cloud computing", "digital"),
    ("00000000-0000-4000-8000-000000000416", "cybersecurity", "Cybersecurity", "digital"),
    ("00000000-0000-4000-8000-000000000417", "data-visualisation", "Data visualisation", "digital"),
    ("00000000-0000-4000-8000-000000000418", "labour-market-analysis", "Labour market analysis", "analytical"),
    ("00000000-0000-4000-8000-000000000419", "curriculum-design", "Curriculum design", "education"),
    ("00000000-0000-4000-8000-000000000420", "quality-assurance", "Quality assurance", "business"),
]

ALIASES = {
    "python": ["python", "py"],
    "java": ["java", "jvm"],
    "javascript": ["javascript", "js", "node", "node.js"],
    "sql": ["sql", "postgres", "postgresql", "mysql", "database query"],
    "machine-learning": ["machine learning", "ml", "deep learning", "neural network", "predictive model"],
    "data-analysis": ["data analysis", "analytics", "analyse data", "data analytics"],
    "statistics": ["statistics", "statistical", "regression", "forecast", "forecasting"],
    "database-management": ["database", "database management", "data storage", "data repository"],
    "software-development": ["software development", "programming", "application development", "coding"],
    "project-management": ["project management", "planning", "project planning"],
    "communication": ["communication", "presentation", "report writing", "stakeholder"],
    "problem-solving": ["problem solving", "critical thinking", "analytical thinking"],
    "research": ["research", "institutional research", "evidence-based"],
    "business-intelligence": ["business intelligence", "bi", "dashboard", "reporting"],
    "cloud-computing": ["cloud", "cloud computing", "aws", "azure"],
    "cybersecurity": ["cybersecurity", "security", "information security"],
    "data-visualisation": ["data visualisation", "data visualization", "visualisation", "visualization"],
    "labour-market-analysis": ["labour market", "labor market", "employment", "unemployment", "workforce"],
    "curriculum-design": ["curriculum", "curriculum design", "learning outcome", "module outcome"],
    "quality-assurance": ["quality assurance", "quality management", "audit", "compliance"],
}


def upgrade() -> None:
    op.create_table(
        "skill",
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_key", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("skill_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("skill_id"),
        sa.UniqueConstraint("skill_key"),
    )
    op.create_index(op.f("ix_skill_skill_key"), "skill", ["skill_key"], unique=True)
    op.create_index(op.f("ix_skill_name"), "skill", ["name"], unique=False)
    op.create_index(op.f("ix_skill_category"), "skill", ["category"], unique=False)
    op.create_index(op.f("ix_skill_status"), "skill", ["status"], unique=False)
    op.create_index("idx_skill_category_status", "skill", ["category", "status"], unique=False)

    op.create_table(
        "esco_skill",
        sa.Column("esco_skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("esco_uri", sa.String(length=1000), nullable=True),
        sa.Column("preferred_label", sa.String(length=255), nullable=False),
        sa.Column("skill_type", sa.String(length=100), nullable=True),
        sa.Column("reuse_level", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=50), nullable=False),
        sa.Column("esco_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("esco_skill_id"),
        sa.UniqueConstraint("esco_uri"),
    )
    op.create_index(op.f("ix_esco_skill_skill_id"), "esco_skill", ["skill_id"], unique=False)
    op.create_index(op.f("ix_esco_skill_preferred_label"), "esco_skill", ["preferred_label"], unique=False)
    op.create_index(op.f("ix_esco_skill_skill_type"), "esco_skill", ["skill_type"], unique=False)
    op.create_index("idx_esco_skill_label_type", "esco_skill", ["preferred_label", "skill_type"], unique=False)

    op.create_table(
        "skill_alias",
        sa.Column("alias_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalised_alias", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("confidence_weight", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alias_id"),
    )
    op.create_index(op.f("ix_skill_alias_skill_id"), "skill_alias", ["skill_id"], unique=False)
    op.create_index(op.f("ix_skill_alias_alias"), "skill_alias", ["alias"], unique=False)
    op.create_index(op.f("ix_skill_alias_normalised_alias"), "skill_alias", ["normalised_alias"], unique=False)
    op.create_index(op.f("ix_skill_alias_is_active"), "skill_alias", ["is_active"], unique=False)
    op.create_index("idx_skill_alias_normalised_active", "skill_alias", ["normalised_alias", "is_active"], unique=False)

    op.create_table(
        "skill_mapping",
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("esco_skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_domain", sa.String(length=50), nullable=False),
        sa.Column("source_entity_type", sa.String(length=100), nullable=False),
        sa.Column("source_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("source_text_hash", sa.String(length=64), nullable=True),
        sa.Column("matched_text", sa.String(length=255), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("evidence_start", sa.Integer(), nullable=True),
        sa.Column("evidence_end", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("mapping_status", sa.String(length=50), nullable=False),
        sa.Column("mapping_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["esco_skill_id"], ["esco_skill.esco_skill_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.skill_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("mapping_id"),
    )
    op.create_index(op.f("ix_skill_mapping_skill_id"), "skill_mapping", ["skill_id"], unique=False)
    op.create_index(op.f("ix_skill_mapping_esco_skill_id"), "skill_mapping", ["esco_skill_id"], unique=False)
    op.create_index(op.f("ix_skill_mapping_source_domain"), "skill_mapping", ["source_domain"], unique=False)
    op.create_index(op.f("ix_skill_mapping_source_entity_type"), "skill_mapping", ["source_entity_type"], unique=False)
    op.create_index(op.f("ix_skill_mapping_source_entity_id"), "skill_mapping", ["source_entity_id"], unique=False)
    op.create_index(op.f("ix_skill_mapping_source_record_id"), "skill_mapping", ["source_record_id"], unique=False)
    op.create_index(op.f("ix_skill_mapping_source_text_hash"), "skill_mapping", ["source_text_hash"], unique=False)
    op.create_index(op.f("ix_skill_mapping_mapping_status"), "skill_mapping", ["mapping_status"], unique=False)
    op.create_index("idx_skill_mapping_source_skill", "skill_mapping", ["source_domain", "source_entity_type", "source_entity_id", "skill_id"], unique=False)
    op.create_index("idx_skill_mapping_confidence", "skill_mapping", ["confidence_score"], unique=False)

    skill_table = sa.table(
        "skill",
        sa.column("skill_id", postgresql.UUID(as_uuid=True)),
        sa.column("skill_key", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("description", sa.Text),
        sa.column("status", sa.String),
        sa.column("skill_metadata", postgresql.JSONB),
    )
    op.bulk_insert(
        skill_table,
        [
            {
                "skill_id": skill_id,
                "skill_key": key,
                "name": name,
                "category": category,
                "description": f"Starter canonical skill for {name}.",
                "status": "active",
                "skill_metadata": {"seed": "stage_6_starter"},
            }
            for skill_id, key, name, category in SKILLS
        ],
    )

    esco_table = sa.table(
        "esco_skill",
        sa.column("esco_skill_id", postgresql.UUID(as_uuid=True)),
        sa.column("skill_id", postgresql.UUID(as_uuid=True)),
        sa.column("esco_uri", sa.String),
        sa.column("preferred_label", sa.String),
        sa.column("skill_type", sa.String),
        sa.column("reuse_level", sa.String),
        sa.column("description", sa.Text),
        sa.column("taxonomy_version", sa.String),
        sa.column("esco_metadata", postgresql.JSONB),
    )
    op.bulk_insert(
        esco_table,
        [
            {
                "esco_skill_id": skill_id.replace("401", "501") if skill_id.endswith("401") else f"00000000-0000-4000-8000-0000000005{int(skill_id[-2:]):02d}",
                "skill_id": skill_id,
                "esco_uri": f"https://data.europa.eu/esco/skill/starter-{key}",
                "preferred_label": name,
                "skill_type": "skill/competence",
                "reuse_level": "cross-sector",
                "description": f"Starter ESCO-compatible concept for {name}.",
                "taxonomy_version": "starter",
                "esco_metadata": {"seed": "stage_6_starter", "full_esco_import_pending": True},
            }
            for skill_id, key, name, category in SKILLS
        ],
    )

    alias_table = sa.table(
        "skill_alias",
        sa.column("alias_id", postgresql.UUID(as_uuid=True)),
        sa.column("skill_id", postgresql.UUID(as_uuid=True)),
        sa.column("alias", sa.String),
        sa.column("normalised_alias", sa.String),
        sa.column("language", sa.String),
        sa.column("source", sa.String),
        sa.column("confidence_weight", sa.Float),
        sa.column("is_active", sa.Boolean),
    )
    alias_rows = []
    counter = 1
    skill_by_key = {key: skill_id for skill_id, key, _, _ in SKILLS}
    for key, aliases in ALIASES.items():
        for alias in aliases:
            alias_rows.append(
                {
                    "alias_id": f"00000000-0000-4000-8000-000000000{600 + counter:03d}",
                    "skill_id": skill_by_key[key],
                    "alias": alias,
                    "normalised_alias": alias.lower(),
                    "language": "en",
                    "source": "stage_6_starter",
                    "confidence_weight": 1.0 if alias == key.replace("-", " ") else 0.86,
                    "is_active": True,
                }
            )
            counter += 1
    op.bulk_insert(alias_table, alias_rows)


def downgrade() -> None:
    op.drop_index("idx_skill_mapping_confidence", table_name="skill_mapping")
    op.drop_index("idx_skill_mapping_source_skill", table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_mapping_status"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_source_text_hash"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_source_record_id"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_source_entity_id"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_source_entity_type"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_source_domain"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_esco_skill_id"), table_name="skill_mapping")
    op.drop_index(op.f("ix_skill_mapping_skill_id"), table_name="skill_mapping")
    op.drop_table("skill_mapping")
    op.drop_index("idx_skill_alias_normalised_active", table_name="skill_alias")
    op.drop_index(op.f("ix_skill_alias_is_active"), table_name="skill_alias")
    op.drop_index(op.f("ix_skill_alias_normalised_alias"), table_name="skill_alias")
    op.drop_index(op.f("ix_skill_alias_alias"), table_name="skill_alias")
    op.drop_index(op.f("ix_skill_alias_skill_id"), table_name="skill_alias")
    op.drop_table("skill_alias")
    op.drop_index("idx_esco_skill_label_type", table_name="esco_skill")
    op.drop_index(op.f("ix_esco_skill_skill_type"), table_name="esco_skill")
    op.drop_index(op.f("ix_esco_skill_preferred_label"), table_name="esco_skill")
    op.drop_index(op.f("ix_esco_skill_skill_id"), table_name="esco_skill")
    op.drop_table("esco_skill")
    op.drop_index("idx_skill_category_status", table_name="skill")
    op.drop_index(op.f("ix_skill_status"), table_name="skill")
    op.drop_index(op.f("ix_skill_category"), table_name="skill")
    op.drop_index(op.f("ix_skill_name"), table_name="skill")
    op.drop_index(op.f("ix_skill_skill_key"), table_name="skill")
    op.drop_table("skill")
