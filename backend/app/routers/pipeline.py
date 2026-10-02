"""
Pipeline orchestration endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.pipeline_run import PipelineRun
from app.core.tenant_scope import assert_entity_access, scope_query
from app.schemas.pipeline import PipelineRunDetailResponse, PipelineRunRequest, PipelineRunResponse
from app.services.pipeline_orchestrator_service import pipeline_orchestrator_service


router = APIRouter(
    prefix="/pipeline",
    tags=["pipeline"],
)


@router.post("/statssa/full-run", response_model=PipelineRunDetailResponse)
def run_statssa_full_pipeline(
    request: PipelineRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    request = request.model_copy(update={"tenant_id": current_user.tenant_id})
    actor_id = getattr(current_user, "identity_id", None)
    return pipeline_orchestrator_service.run_statssa_full_pipeline(
        db=db,
        request=request,
        actor_id=actor_id,
    )


@router.get("/runs", response_model=list[PipelineRunResponse])
def list_pipeline_runs(
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        scope_query(db.query(PipelineRun), PipelineRun, current_user)
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/runs/{pipeline_run_id}", response_model=PipelineRunDetailResponse)
def get_pipeline_run(
    pipeline_run_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = pipeline_orchestrator_service.get_run(db, pipeline_run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found",
        )
    assert_entity_access(run, current_user)
    return run
