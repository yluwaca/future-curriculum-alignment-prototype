"""
SA OFO (Organising Framework for Occupations) import service.

Imports OFO taxonomy data (occupations and skills) aligned with
the SA OiHD (Occupations in High Demand) framework.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.data.ofo_seed import (
    get_seed_groups,
    get_seed_occupations,
    get_seed_skills,
)
from app.models.ofo_taxonomy import (
    OFOOccupation,
    OFOOccupationSkillLink,
    OFOSkill,
)
from app.models.skill import Skill


logger = logging.getLogger(__name__)


class OFOImportService:
    """
    Handles importing OFO taxonomy data (seeds, file uploads).

    Paper reference: Maps SA OFO occupations to internal skills for
    curriculum-labour market alignment.
    """

    TAXONOMY_VERSION = "ofo_v1_2024"

    def __init__(self, db: Session):
        self.db = db

    def import_seed_data(self) -> Dict[str, Any]:
        """
        Import OFO seed data: groups, occupations, and skills.
        Used for initial setup and testing.
        """
        counts = {"groups": 0, "occupations": 0, "skills": 0, "links": 0}

        # 1. Import groups (top_concept and sub-groups)
        parent_cache: Dict[str, Optional[UUID]] = {}
        for group in get_seed_groups():
            existing = (
                self.db.query(OFOSkill)
                .filter(OFOSkill.ofo_code == group["ofo_code"])
                .first()
            )
            if existing:
                parent_id = existing.ofo_skill_id
            else:
                parent_id = uuid4()
                parent_uuid = None
                parent_code = group.get("parent_code")
                if parent_code and parent_code in parent_cache:
                    parent_uuid = parent_cache[parent_code]
                obj = OFOSkill(
                    ofo_skill_id=parent_id,
                    ofo_code=group["ofo_code"],
                    preferred_label=group["preferred_label"],
                    description=group.get("description"),
                    skill_type=group.get("skill_type", "occupation_group"),
                    top_concept=group.get("top_concept", False),
                    parent_id=parent_uuid,
                    taxonomy_version=self.TAXONOMY_VERSION,
                )
                self.db.add(obj)
                counts["groups"] += 1
            parent_cache[group["ofo_code"]] = parent_id

        self.db.flush()

        # 2. Import occupations
        occ_cache: Dict[str, UUID] = {}
        for occ in get_seed_occupations():
            existing = (
                self.db.query(OFOOccupation)
                .filter(OFOOccupation.ofo_code == occ["ofo_code"])
                .first()
            )
            if existing:
                occ_id = existing.ofo_occupation_id
            else:
                occ_id = uuid4()
                obj = OFOOccupation(
                    ofo_occupation_id=occ_id,
                    ofo_code=occ["ofo_code"],
                    preferred_label=occ["preferred_label"],
                    description=occ.get("description"),
                    status="active",
                    taxonomy_version=self.TAXONOMY_VERSION,
                    broader_occupation_code=occ.get("parent_code"),
                )
                self.db.add(obj)
                counts["occupations"] += 1
            occ_cache[occ["ofo_code"]] = occ_id

            # Import skills linked to this occupation
            for skill_name in occ.get("skills", []):
                skill = self._get_or_create_skill(skill_name)
                if skill.ofo_skills:
                    ofo_skill = skill.ofo_skills[0]
                else:
                    ofo_skill = self._link_skill_to_ofo(skill, occ_id)
                counts["skills"] += 1

                # Create occupation-skill link
                existing_link = (
                    self.db.query(OFOOccupationSkillLink)
                    .filter(
                        OFOOccupationSkillLink.occupation_id == occ_id,
                        OFOOccupationSkillLink.skill_id == ofo_skill.ofo_skill_id,
                    )
                    .first()
                )
                if not existing_link:
                    link = OFOOccupationSkillLink(
                        occupation_id=occ_id,
                        skill_id=ofo_skill.ofo_skill_id,
                        relationship_type="essential",
                    )
                    self.db.add(link)
                    counts["links"] += 1

        self.db.commit()
        logger.info(
            "[OFO] Seed import complete: %d groups, %d occupations, %d skills, %d links",
            counts["groups"], counts["occupations"], counts["skills"], counts["links"],
        )
        return counts

    def _get_or_create_skill(self, skill_name: str) -> Skill:
        skill_key = skill_name.lower().replace(" ", "-").replace("/", "-")
        skill = (
            self.db.query(Skill)
            .filter(Skill.skill_key == skill_key)
            .first()
        )
        if not skill:
            skill = Skill(
                skill_key=skill_key,
                name=skill_name.title(),
                category="transversal",
                description=f"SA OFO skill: {skill_name}",
            )
            self.db.add(skill)
            self.db.flush()
        return skill

    def _link_skill_to_ofo(self, skill: Skill, occ_id: UUID) -> OFOSkill:
        ofo_skill = OFOSkill(
            skill_id=skill.skill_id,
            ofo_code=f"OFO-{skill.skill_key[:10]}",
            preferred_label=skill.name,
            skill_type="skill/competence",
            taxonomy_version=self.TAXONOMY_VERSION,
            description=f"Mapped from SA OFO occupation: {skill.name}",
        )
        self.db.add(ofo_skill)
        self.db.flush()
        return ofo_skill

    def get_coverage_stats(self) -> Dict[str, Any]:
        """Return coverage statistics for OFO taxonomy."""
        occ_count = self.db.query(OFOOccupation).count()
        skill_count = self.db.query(OFOSkill).count()
        link_count = self.db.query(OFOOccupationSkillLink).count()
        linked_to_canonical = (
            self.db.query(OFOSkill)
            .filter(OFOSkill.skill_id.isnot(None))
            .count()
        )
        return {
            "occupations": occ_count,
            "skills": skill_count,
            "occupation_skill_links": link_count,
            "skills_linked_to_canonical": linked_to_canonical,
            "taxonomy_version": self.TAXONOMY_VERSION,
        }
