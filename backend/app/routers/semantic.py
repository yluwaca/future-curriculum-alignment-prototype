"""
Vector repository and semantic search endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.semantic import (
    CurriculumIndexRequest,
    CurriculumIndexResponse,
    SemanticSearchRequest,
    SemanticSearchResponse,
    VectorRepositoryStatusResponse,
)
from app.services.semantic_vector_service import PgvectorNotReadyError, semantic_vector_service


router = APIRouter(
    prefix="/semantic",
    tags=["semantic-search"],
)


@router.get(
    "/vector/status",
    response_model=VectorRepositoryStatusResponse,
)
def vector_repository_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return semantic_vector_service.status(db)


@router.post(
    "/index/curriculum",
    response_model=CurriculumIndexResponse,
)
def index_curriculum_chunks(
    request: CurriculumIndexRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return semantic_vector_service.index_curriculum_chunks(
            db=db,
            version_id=request.version_id,
            limit=request.limit,
        )
    except PgvectorNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Vector repository is not ready: {exc}",
        ) from exc


@router.post(
    "/search",
    response_model=SemanticSearchResponse,
)
def semantic_search(
    request: SemanticSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return semantic_vector_service.semantic_search(
            db=db,
            query_text=request.query,
            actor_id=current_user.identity_id,
            top_k=request.top_k,
            source_entity_type=request.source_entity_type,
            min_score=request.min_score,
        )
    except PgvectorNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Vector repository is not ready: {exc}",
        ) from exc
