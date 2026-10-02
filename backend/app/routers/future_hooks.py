"""
Future-ready architecture hook endpoints.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.future_hooks import (
    ConnectorHookResponse,
    HookHealthResponse,
    HookResultResponse,
    LLMRAGQueryRequest,
    ModelDriftCheckRequest,
    ScenarioSimulationRequest,
)
from app.services.future_hooks.intelligence_services import (
    llm_rag_service,
    model_drift_monitoring_service,
    scenario_simulation_service,
)
from app.services.future_hooks.registry import future_hook_registry


router = APIRouter(
    prefix="/future-hooks",
    tags=["future-hooks"],
)


@router.get(
    "/connectors",
    response_model=List[ConnectorHookResponse],
)
def list_connectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return [
        future_hook_registry.connector_metadata(db, connector)
        for connector in future_hook_registry.list_connectors()
    ]


@router.get(
    "/connectors/{connector_key}",
    response_model=ConnectorHookResponse,
)
def get_connector(
    connector_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = future_hook_registry.get_connector(connector_key)
    if not connector:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Future connector hook not found",
        )

    return future_hook_registry.connector_metadata(db, connector)


@router.post(
    "/connectors/{connector_key}/health-check",
    response_model=HookHealthResponse,
)
def connector_health_check(
    connector_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    health = future_hook_registry.health_check(db, connector_key)
    if not health:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Future connector hook not found",
        )

    return health


@router.post(
    "/llm-rag/query",
    response_model=HookResultResponse,
)
def query_llm_rag(
    payload: LLMRAGQueryRequest,
    current_user: User = Depends(get_current_user),
):
    return llm_rag_service.query(
        question=payload.question,
        context_filters=payload.context_filters,
        top_k=payload.top_k,
    )


@router.post(
    "/scenarios/simulate",
    response_model=HookResultResponse,
)
def simulate_scenario(
    payload: ScenarioSimulationRequest,
    current_user: User = Depends(get_current_user),
):
    return scenario_simulation_service.simulate(
        scenario_name=payload.scenario_name,
        assumptions=payload.assumptions,
    )


@router.post(
    "/model-drift/check",
    response_model=HookResultResponse,
)
def check_model_drift(
    payload: ModelDriftCheckRequest,
    current_user: User = Depends(get_current_user),
):
    return model_drift_monitoring_service.check(
        model_key=payload.model_key,
        metric_names=payload.metric_names,
        window=payload.window,
    )

