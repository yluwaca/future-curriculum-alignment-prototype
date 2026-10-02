"""
Vector enrichment endpoints.

Embeds ESCO taxonomy and matches arbitrary text against it via cosine similarity.
Supports enriching job postings, curriculum documents, and any other source.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models.user import User
from app.services.vector_enrichment_service import vector_enrichment_service


router = APIRouter(
    prefix="/enrichment",
    tags=["vector-enrichment"],
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class EnrichTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000, description="Text to enrich")
    top_skill_k: int = Field(10, ge=1, le=50)
    top_occ_k: int = Field(5, ge=1, le=20)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


class EnrichTextResponse(BaseModel):
    text_preview: str
    skill_matches: List[Dict[str, Any]]
    occupation_matches: List[Dict[str, Any]]


class EnrichJobPostingsRequest(BaseModel):
    limit: int = Field(500, ge=1, le=5000, description="Max postings to enrich")
    top_skill_k: int = Field(10, ge=1, le=50)
    top_occ_k: int = Field(3, ge=1, le=20)
    min_skill_score: float = Field(0.35, ge=0.0, le=1.0)
    min_occ_score: float = Field(0.35, ge=0.0, le=1.0)


class EnrichJobPostingsResponse(BaseModel):
    enriched: int
    errors: int
    total_skill_matches: int
    total_occupation_matches: int
    esco_index: Dict[str, Any]
    sample_results: List[Dict[str, Any]]


class SearchSimilarSkillsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(10, ge=1, le=50)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


class SearchSimilarOccupationsRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(5, ge=1, le=20)
    min_score: float = Field(0.3, ge=0.0, le=1.0)


class BuildIndexResponse(BaseModel):
    skills: int
    occupations: int
    build_time_s: float
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/build-index", response_model=BuildIndexResponse)
def build_esco_index(
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dataset.read")),
):
    """Build or rebuild the ESCO embedding index in memory.

    Call this after importing new ESCO data or to refresh the cache.
    """
    index = vector_enrichment_service.build_esco_index(db, force=force)
    return BuildIndexResponse(
        skills=index["skill_count"],
        occupations=index["occupation_count"],
        build_time_s=index["build_time_s"],
        message="ESCO index built successfully",
    )


@router.post("/search/skills")
def search_similar_skills(
    request: SearchSimilarSkillsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dataset.read")),
):
    """Find ESCO skills most similar to the given text."""
    return vector_enrichment_service.find_similar_skills(
        text=request.text,
        db=db,
        top_k=request.top_k,
        min_score=request.min_score,
    )


@router.post("/search/occupations")
def search_similar_occupations(
    request: SearchSimilarOccupationsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dataset.read")),
):
    """Find ESCO occupations most similar to the given text."""
    return vector_enrichment_service.find_similar_occupations(
        text=request.text,
        db=db,
        top_k=request.top_k,
        min_score=request.min_score,
    )


@router.post("/enrich/text", response_model=EnrichTextResponse)
def enrich_text(
    request: EnrichTextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dataset.read")),
):
    """Enrich arbitrary text with ESCO skill and occupation matches.

    Useful for curriculum documents, job descriptions, or any free-form text.
    """
    return vector_enrichment_service.enrich_text(
        text_content=request.text,
        db=db,
        top_skill_k=request.top_skill_k,
        top_occ_k=request.top_occ_k,
        min_score=request.min_score,
    )


@router.post("/enrich/job-postings", response_model=EnrichJobPostingsResponse)
def enrich_job_postings_batch(
    request: EnrichJobPostingsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dataset.write")),
):
    """Enrich a batch of unprocessed job postings with ESCO matches.

    Finds postings where embedding_generated=False or is_processed=False,
    enriches them with ESCO skill and occupation matches, and returns summary.
    """
    return vector_enrichment_service.enrich_job_postings_batch(
        db=db,
        limit=request.limit,
        top_skill_k=request.top_skill_k,
        top_occ_k=request.top_occ_k,
        min_skill_score=request.min_skill_score,
        min_occ_score=request.min_occ_score,
    )


@router.get("/status")
def enrichment_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current status of the enrichment service."""
    from app.services.semantic_vector_service import semantic_vector_service

    vec_status = semantic_vector_service.status(db)
    index = vector_enrichment_service.build_esco_index(db)

    return {
        "vector_backend": vec_status.get("active_storage_backend", "unknown"),
        "pgvector_enabled": vec_status.get("pgvector_installed", False),
        "vector_readiness": vec_status.get("readiness_status", "unknown"),
        "esco_index": {
            "skills": index["skill_count"],
            "occupations": index["occupation_count"],
            "build_time_s": index["build_time_s"],
        },
    }
