"""
SA OFO (Organising Framework for Occupations) API router.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.ofo_taxonomy import OFOOccupation, OFOOccupationSkillLink, OFOSkill
from app.models.skill import Skill
from app.services.ofo_import_service import OFOImportService
from app.core.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_enabled():
    if not settings.ENABLE_OFO_TAXONOMY:
        raise HTTPException(status_code=404, detail="OFO taxonomy feature is disabled")


@router.post("/ofo/import", response_model=Dict[str, Any])
async def import_ofo_seeds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import OFO seed taxonomy data (groups, occupations, skills)."""
    _check_enabled()
    service = OFOImportService(db)
    counts = service.import_seed_data()
    return {"status": "ok", "imported": counts}


@router.get("/ofo/occupations", response_model=List[Dict[str, Any]])
async def list_occupations(
    search: str = Query(None, min_length=2),
    parent_code: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List OFO occupations with optional search."""
    _check_enabled()
    query = db.query(OFOOccupation).filter(OFOOccupation.status == "active")
    if search:
        escaped = search.replace("%", "\\%").replace("_", "\\_")
        query = query.filter(OFOOccupation.preferred_label.ilike(f"%{escaped}%"))
    if parent_code:
        query = query.filter(OFOOccupation.broader_occupation_code == parent_code)
    query = query.order_by(OFOOccupation.preferred_label).offset(skip).limit(limit)
    occs = query.all()
    return [
        {
            "ofo_occupation_id": str(o.ofo_occupation_id),
            "ofo_code": o.ofo_code,
            "preferred_label": o.preferred_label,
            "description": o.description,
            "status": o.status,
        }
        for o in occs
    ]


@router.get("/ofo/occupations/{occupation_id}", response_model=Dict[str, Any])
async def get_occupation(
    occupation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get OFO occupation detail with linked skills."""
    _check_enabled()
    occ = (
        db.query(OFOOccupation)
        .filter(OFOOccupation.ofo_occupation_id == occupation_id)
        .first()
    )
    if not occ:
        raise HTTPException(status_code=404, detail="Occupation not found")

    links = (
        db.query(OFOOccupationSkillLink, OFOSkill, Skill)
        .join(OFOSkill, OFOSkill.ofo_skill_id == OFOOccupationSkillLink.skill_id)
        .join(Skill, Skill.skill_id == OFOSkill.skill_id, isouter=True)
        .filter(OFOOccupationSkillLink.occupation_id == occupation_id)
        .all()
    )

    skills_list = []
    for link, ofo_skill, canonical_skill in links:
        skills_list.append({
            "ofo_skill_id": str(ofo_skill.ofo_skill_id),
            "preferred_label": ofo_skill.preferred_label,
            "skill_type": link.skill_type or ofo_skill.skill_type,
            "relationship_type": link.relationship_type,
            "canonical_skill_id": str(canonical_skill.skill_id) if canonical_skill else None,
            "canonical_skill_name": canonical_skill.name if canonical_skill else ofo_skill.preferred_label,
        })

    return {
        "ofo_occupation_id": str(occ.ofo_occupation_id),
        "ofo_code": occ.ofo_code,
        "preferred_label": occ.preferred_label,
        "description": occ.description,
        "status": occ.status,
        "skills": skills_list,
        "top_concept": occ.top_concept,
    }


@router.get("/ofo/skills", response_model=List[Dict[str, Any]])
async def list_skills(
    search: str = Query(None, min_length=2),
    skill_type: str = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List OFO skills."""
    _check_enabled()
    query = db.query(OFOSkill).filter(~OFOSkill.top_concept)
    if search:
        escaped = search.replace("%", "\\%").replace("_", "\\_")
        query = query.filter(OFOSkill.preferred_label.ilike(f"%{escaped}%"))
    if skill_type:
        query = query.filter(OFOSkill.skill_type == skill_type)
    query = query.order_by(OFOSkill.preferred_label).offset(skip).limit(limit)
    skills = query.all()
    return [
        {
            "ofo_skill_id": str(s.ofo_skill_id),
            "preferred_label": s.preferred_label,
            "skill_type": s.skill_type,
            "ofo_code": s.ofo_code,
            "top_concept": s.top_concept,
        }
        for s in skills
    ]


@router.get("/ofo/stats", response_model=Dict[str, Any])
async def get_ofo_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get OFO taxonomy coverage statistics."""
    _check_enabled()
    service = OFOImportService(db)
    stats = service.get_coverage_stats()
    stats["enabled"] = settings.ENABLE_OFO_TAXONOMY
    return stats
