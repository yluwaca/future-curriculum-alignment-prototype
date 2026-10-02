"""
Schemas for future-ready architecture hook APIs.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


MODEL_CONFIG = ConfigDict(from_attributes=True)


class HookHealthResponse(BaseModel):
    status: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

    model_config = MODEL_CONFIG


class HookResultResponse(BaseModel):
    status: str
    message: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    model_config = MODEL_CONFIG


class ConnectorHookResponse(BaseModel):
    connector_key: str
    display_name: str
    source_category: str
    source_type: str
    connector_type: str
    capabilities: List[str]
    registered_source_id: Optional[str]
    source_status: str
    is_authorised: bool
    health: HookHealthResponse

    model_config = MODEL_CONFIG


class LLMRAGQueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    context_filters: Dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=25)


class ScenarioSimulationRequest(BaseModel):
    scenario_name: str = Field(..., min_length=1, max_length=255)
    assumptions: Dict[str, Any] = Field(default_factory=dict)


class ModelDriftCheckRequest(BaseModel):
    model_key: str = Field(..., min_length=1, max_length=100)
    metric_names: List[str] = Field(default_factory=list)
    window: str = Field(default="latest")

    model_config = ConfigDict(protected_namespaces=())
