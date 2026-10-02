"""
Schemas for labour-market trend normalisation APIs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ingestion import IngestionJobResponse


ORM_CONFIG = ConfigDict(from_attributes=True)


class TrendNormaliseRequest(BaseModel):
    job_id: Optional[UUID] = None
    limit: int = Field(default=1000, ge=1, le=10000)


class TrendNormaliseResponse(BaseModel):
    records_seen: int
    records_skipped: int
    trend_facts_seen: int
    trend_facts_inserted: int


class TrendSummaryResponse(BaseModel):
    total_trends: int
    total_signals: int = 0
    by_dimension_type: Dict[str, int]
    by_canonical_signal: Dict[str, int] = {}
    recent_periods: List[Dict[str, Any]]


class SignalGenerateRequest(BaseModel):
    limit: int = Field(default=50000, ge=1, le=100000)


class SignalGenerateResponse(BaseModel):
    trend_facts_seen: int
    trend_facts_skipped: int
    signals_seen: int
    signals_inserted: int


class JobAdvertUploadResponse(BaseModel):
    message: str
    job: IngestionJobResponse
    rows_seen: int
    inserted: int
    updated: int
    skipped: int
    failed: int


class LabourMarketSkillPipelineRequest(BaseModel):
    limit: int = Field(default=10000, ge=1, le=50000)
    offset: int = Field(default=0, ge=0)
    sources: Optional[List[str]] = Field(
        default=None,
        description="Optional list of JobPosting.source labels to scope the pipeline run to.",
    )


class LabourMarketSkillPipelineStageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class LabourMarketSkillPipelineResponse(BaseModel):
    actor_id: Optional[str]
    offset: int
    limit: int
    cleaned: Dict[str, Any]
    mappings: Dict[str, Any]
    signals: Dict[str, Any]
    evidence: Dict[str, Any]
    run_id: Optional[str] = None
    sources: List[str] = Field(default_factory=list)
    ingestion_job_ids: List[str] = Field(default_factory=list)
    trial_scope: Dict[str, Any] = Field(default_factory=dict)


class LabourMarketSkillSignalRequest(BaseModel):
    limit: int = Field(default=10000, ge=1, le=100000)
    sources: Optional[List[str]] = Field(
        default=None,
        description="Optional list of JobPosting.source labels to scope signal/evidence generation to.",
    )


class LabourMarketSkillSignalResponse(BaseModel):
    mappings_considered: int = 0
    mappings_approved_used: int = 0
    signals_seen: int = 0
    signals_created: int = 0
    signals_updated: int = 0
    evidence_seen: int = 0
    evidence_created: int = 0
    evidence_skipped: int = 0
    promotion_gate: str = "approved_labour_mappings_only"
    sources: List[str] = Field(default_factory=list)
    ingestion_job_ids: List[str] = Field(default_factory=list)
    trial_scope: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


class JobPostingResponse(BaseModel):
    posting_id: UUID
    job_id: str
    job_title: str
    job_description: Optional[str]
    required_skills: Optional[Dict[str, Any]]
    education_level: Optional[str]
    experience_years: Optional[int]
    region: str
    country: str
    employment_type: Optional[str]
    salary_min: Optional[float]
    salary_max: Optional[float]
    posted_date: datetime
    closed_date: Optional[datetime]
    posting_year: int
    posting_month: int
    posting_quarter: int
    source: Optional[str]
    source_url: Optional[str]
    is_processed: bool
    embedding_generated: bool
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class LabourMarketTrendResponse(BaseModel):
    trend_id: UUID
    cleaned_record_id: UUID
    raw_record_id: Optional[UUID]
    job_id: Optional[UUID]
    source_id: Optional[UUID]
    indicator_name: str
    measure_name: str
    dimension_type: str
    dimension_value: Optional[str]
    year: int
    quarter: str
    value: float
    unit: Optional[str]
    source_file: Optional[str]
    table_title: Optional[str]
    observation_hash: str
    extraction_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class LabourMarketSignalResponse(BaseModel):
    signal_id: UUID
    canonical_key: str
    canonical_name: str
    signal_type: str
    dimension_type: str
    dimension_value: Optional[str]
    year: int
    quarter: str
    observed_value: float
    normalised_value: float
    demand_score: float
    confidence_score: float
    evidence_count: int
    unit: Optional[str]
    method: str
    source_summary: Optional[str]
    signal_hash: str
    signal_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG
