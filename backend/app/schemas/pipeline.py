"""
Schemas for pipeline orchestration APIs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ORM_CONFIG = ConfigDict(from_attributes=True)


class PipelineRunRequest(BaseModel):
    tenant_id: Optional[UUID] = None
    start_year: int = Field(default=2010, ge=1990, le=2100)
    end_year: int = Field(default=2010, ge=1990, le=2100)
    parse: bool = True
    dry_run: bool = False
    max_files: Optional[int] = Field(default=1, ge=1, le=500)
    quality_limit: int = Field(default=1000, ge=1, le=100000)
    trend_limit: int = Field(default=10000, ge=1, le=200000)
    signal_limit: int = Field(default=50000, ge=1, le=500000)
    evidence_limit: int = Field(default=10000, ge=1, le=200000)
    horizon_periods: int = Field(default=4, ge=1, le=24)
    report_limit: int = Field(default=3, ge=0, le=25)
    skip_ingestion: bool = False
    existing_job_id: Optional[UUID] = None


class PipelineStageRunResponse(BaseModel):
    stage_run_id: UUID
    pipeline_run_id: UUID
    stage_key: str
    stage_name: str
    sequence_number: int
    status: str
    input_summary: Dict[str, Any]
    output_summary: Dict[str, Any]
    error_summary: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class PipelineRunResponse(BaseModel):
    pipeline_run_id: UUID
    pipeline_key: str
    tenant_id: Optional[UUID] = None
    run_scope: str = "shared"
    status: str
    triggered_by: Optional[str]
    parameters: Dict[str, Any]
    summary: Dict[str, Any]
    error_summary: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class PipelineRunDetailResponse(PipelineRunResponse):
    stages: List[PipelineStageRunResponse] = Field(default_factory=list)
