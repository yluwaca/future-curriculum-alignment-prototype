"""
Schemas for dynamic ingestion APIs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ORM_CONFIG = ConfigDict(from_attributes=True)


class DataSourceCreate(BaseModel):
    tenant_id: Optional[UUID] = None
    connector_definition_id: Optional[UUID] = None
    source_key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    source_type: str = Field(..., min_length=1, max_length=50)
    source_category: str = Field(..., min_length=1, max_length=50)
    connector_type: str = Field(..., min_length=1, max_length=100)
    source_scope: str = Field(default="shared", pattern="^(shared|tenant)$")
    ingestion_mode: str = Field(default="batch", pattern="^(manual|batch|scheduled|streaming)$")
    source_format: str = Field(default="unknown", min_length=1, max_length=80)
    normaliser_key: Optional[str] = None
    base_url: Optional[str] = None
    storage_path: Optional[str] = None
    refresh_policy: Optional[str] = None
    retry_policy: Dict[str, Any] = Field(default_factory=dict)
    owner: Optional[str] = None
    status: str = "active"
    is_authorised: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)
    auth_config: Dict[str, Any] = Field(default_factory=dict)


class DataSourceUpdate(BaseModel):
    tenant_id: Optional[UUID] = None
    connector_definition_id: Optional[UUID] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    source_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    source_category: Optional[str] = Field(default=None, min_length=1, max_length=50)
    connector_type: Optional[str] = Field(default=None, min_length=1, max_length=100)
    source_scope: Optional[str] = Field(default=None, pattern="^(shared|tenant)$")
    ingestion_mode: Optional[str] = Field(default=None, pattern="^(manual|batch|scheduled|streaming)$")
    source_format: Optional[str] = Field(default=None, min_length=1, max_length=80)
    normaliser_key: Optional[str] = None
    base_url: Optional[str] = None
    storage_path: Optional[str] = None
    refresh_policy: Optional[str] = None
    retry_policy: Optional[Dict[str, Any]] = None
    owner: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|disabled|error)$")
    is_authorised: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    auth_config: Optional[Dict[str, Any]] = None


class DataSourceResponse(DataSourceCreate):
    source_id: UUID
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    consecutive_failures: int = 0
    circuit_state: str = "closed"
    circuit_open_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ConnectorDefinitionResponse(BaseModel):
    connector_definition_id: UUID
    connector_key: str
    name: str
    connector_family: str
    ingestion_mode: str
    source_category: str
    source_format: str
    normaliser_key: Optional[str]
    is_streaming_capable: bool
    requires_auth: bool
    description: Optional[str]
    capability_profile: Dict[str, Any]
    default_config: Dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ConnectorDefinitionCreate(BaseModel):
    connector_key: str = Field(..., min_length=1, max_length=150)
    name: str = Field(..., min_length=1, max_length=255)
    connector_family: str = Field(..., min_length=1, max_length=100)
    ingestion_mode: str = Field(default="batch", pattern="^(manual|batch|scheduled|streaming)$")
    source_category: str = Field(..., min_length=1, max_length=80)
    source_format: str = Field(default="unknown", min_length=1, max_length=80)
    normaliser_key: Optional[str] = None
    is_streaming_capable: bool = False
    requires_auth: bool = False
    description: Optional[str] = None
    capability_profile: Dict[str, Any] = Field(default_factory=dict)
    default_config: Dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="active", pattern="^(active|inactive|disabled|deprecated)$")


class ConnectorDefinitionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    connector_family: Optional[str] = Field(default=None, min_length=1, max_length=100)
    ingestion_mode: Optional[str] = Field(default=None, pattern="^(manual|batch|scheduled|streaming)$")
    source_category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    source_format: Optional[str] = Field(default=None, min_length=1, max_length=80)
    normaliser_key: Optional[str] = None
    is_streaming_capable: Optional[bool] = None
    requires_auth: Optional[bool] = None
    description: Optional[str] = None
    capability_profile: Optional[Dict[str, Any]] = None
    default_config: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|disabled|deprecated)$")


class NormaliserDefinitionResponse(BaseModel):
    normaliser_definition_id: UUID
    normaliser_key: str
    name: str
    version: str
    source_category: str
    input_format: str
    output_record_type: str
    supported_record_types: List[str]
    transformation_profile: Dict[str, Any]
    output_schema: Dict[str, Any]
    is_default: bool
    status: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class SourceClassificationResponse(BaseModel):
    source_id: UUID
    source_key: str
    tenant_id: Optional[UUID]
    source_scope: str
    source_category: str
    source_type: str
    connector_type: str
    connector_definition_id: Optional[UUID]
    ingestion_mode: str
    source_format: str
    normaliser_key: Optional[str]
    is_shared_platform_source: bool
    is_tenant_source: bool
    resilience: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any]


class ConnectorHealthResponse(BaseModel):
    source_id: UUID
    source_key: str
    status: str
    reachable: bool
    storage_available: bool
    message: str
    checked_at: datetime
    details: Dict[str, Any] = Field(default_factory=dict)


class ConnectorScheduleResponse(BaseModel):
    source_id: UUID
    source_key: str
    refresh_policy: Optional[str]
    schedule: Dict[str, Any] = Field(default_factory=dict)
    retry_policy: Dict[str, Any] = Field(default_factory=dict)


class ConnectorScheduleUpdate(BaseModel):
    refresh_policy: Optional[str] = None
    schedule: Dict[str, Any] = Field(default_factory=dict)
    retry_policy: Dict[str, Any] = Field(default_factory=dict)


class CredentialTestRequest(BaseModel):
    auth_config: Dict[str, Any] = Field(default_factory=dict)


class CredentialSaveRequest(BaseModel):
    auth_config: Dict[str, Any] = Field(default_factory=dict)


class CredentialStatusResponse(BaseModel):
    source_id: UUID
    source_key: str
    has_credentials: bool
    auth_config: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: Optional[str] = None


class JobBoardSimulationRequest(BaseModel):
    provider: str = Field(..., pattern="^(linkedin|indeed|pnet|careerjunction)$")
    tenant_id: Optional[UUID] = None
    source_label: Optional[str] = None
    payloads: List[Dict[str, Any]] = Field(default_factory=list)
    use_sample_when_empty: bool = True


class JobBoardSimulationResponse(BaseModel):
    job_id: str
    source_id: str
    provider: str
    records_seen: int
    inserted: int
    updated: int
    failed: int


class SourceFreshnessResponse(BaseModel):
    source_id: UUID
    source_key: str
    tenant_id: Optional[UUID]
    name: str
    source_category: str
    source_type: str
    status: str
    last_success_at: Optional[datetime]
    last_failure_at: Optional[datetime]
    latest_record_at: Optional[datetime]
    latest_archive_at: Optional[datetime]
    freshness_status: str
    records_seen: int = 0
    records_loaded: int = 0
    records_failed: int = 0


class DueScheduleResponse(BaseModel):
    source_id: UUID
    source_key: str
    name: str
    due: bool
    reason: str
    next_run_hint: Optional[str] = None
    schedule: Dict[str, Any] = Field(default_factory=dict)


class ContractCloneRequest(BaseModel):
    version: str = Field(..., min_length=1, max_length=50)
    name: Optional[str] = None
    status: str = Field(default="draft", pattern="^(draft|active|inactive|deprecated)$")


class SourceFileArchiveResponse(BaseModel):
    source_id: Optional[UUID]
    source_key: Optional[str]
    storage_uri: Optional[str]
    source_file: Optional[str]
    content_hash: Optional[str]
    first_seen_at: datetime
    latest_seen_at: datetime
    record_count: int
    duplicate_count: int
    record_types: List[str]
    freshness_status: str


class IngestionJobResponse(BaseModel):
    job_id: UUID
    source_id: Optional[UUID]
    source_key: Optional[str] = None
    source_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    job_type: str
    status: str
    triggered_by: Optional[str]
    parameters: Dict[str, Any]
    progress_current: int
    progress_total: int
    records_seen: int
    records_loaded: int
    records_failed: int
    processed: bool = False
    imported: bool = False
    error_summary: Optional[str]
    attempt_number: int = 1
    max_attempts: int = 3
    retry_of_job_id: Optional[UUID] = None
    failure_category: Optional[str] = None
    failure_stage: Optional[str] = None
    failure_details: Dict[str, Any] = Field(default_factory=dict)
    retry_backoff_seconds: int = 0
    next_retry_at: Optional[datetime] = None
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    last_heartbeat_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class StatsSAJobRequest(BaseModel):
    start_year: int = Field(default=2010, ge=1990, le=2100)
    end_year: int = Field(default=2025, ge=1990, le=2100)
    parse: bool = False
    dry_run: bool = False
    max_files: Optional[int] = Field(default=None, ge=1, le=500)


class CHEVitalStatsJobRequest(BaseModel):
    start_year: int = Field(default=2010, ge=1990, le=2100)
    end_year: int = Field(default=2022, ge=1990, le=2100)
    parse: bool = False
    dry_run: bool = True
    max_files: Optional[int] = Field(default=1, ge=1, le=100)


class StatsSAJobStartResponse(BaseModel):
    message: str
    job: IngestionJobResponse
    operational_job: Optional[Dict[str, Any]] = None


class IngestionRetryResponse(BaseModel):
    message: str
    original_job: IngestionJobResponse
    retry_job: IngestionJobResponse


class IngestionFailureEventResponse(BaseModel):
    failure_id: UUID
    job_id: UUID
    source_id: Optional[UUID]
    tenant_id: Optional[UUID]
    event_time: datetime
    failure_stage: str
    failure_category: str
    severity: str
    message: str
    retryable: str
    attempt_number: int
    next_retry_at: Optional[datetime]
    diagnostic_payload: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RawRecordResponse(BaseModel):
    record_id: UUID
    job_id: UUID
    source_id: Optional[UUID]
    source_key: Optional[str] = None
    source_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    source_category: Optional[str] = None
    source_name: Optional[str] = None
    source_record_id: Optional[str]
    record_type: str
    storage_uri: Optional[str]
    content_hash: Optional[str]
    validation_status: str
    raw_payload: Dict[str, Any]
    normalised_payload: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class LineageEventResponse(BaseModel):
    lineage_id: UUID
    event_time: datetime
    job_id: Optional[UUID]
    source_id: Optional[UUID]
    input_record_id: Optional[UUID]
    output_record_id: Optional[UUID]
    source_system: str
    processing_stage: str
    transformation_description: str
    actor_id: Optional[str]
    lineage_metadata: Dict[str, Any]

    model_config = ORM_CONFIG


class ExtractedTableResponse(BaseModel):
    table_id: UUID
    job_id: UUID
    source_id: Optional[UUID]
    raw_record_id: Optional[UUID]
    source_file: str
    document_uri: Optional[str]
    page_number: Optional[int]
    table_index: Optional[int]
    title: Optional[str]
    year: Optional[int]
    quarter: Optional[str]
    series_code: Optional[str]
    row_count: int
    column_count: int
    columns: List[Any]
    extraction_method: str
    extraction_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ExtractedTableRowResponse(BaseModel):
    row_id: UUID
    table_id: UUID
    row_number: int
    row_payload: Dict[str, Any]
    normalised_payload: Dict[str, Any]
    content_hash: str
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class IngestionContractResponse(BaseModel):
    contract_id: UUID
    source_id: UUID
    contract_key: str
    name: str
    version: str
    record_type: str
    description: Optional[str]
    schema_definition: Dict[str, Any]
    cleaning_profile: Dict[str, Any]
    quality_thresholds: Dict[str, Any]
    status: str
    effective_from: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class IngestionContractUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    schema_definition: Optional[Dict[str, Any]] = None
    cleaning_profile: Optional[Dict[str, Any]] = None
    quality_thresholds: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(default=None, pattern="^(active|inactive|deprecated)$")


class ContractDriftReportResponse(BaseModel):
    contract_id: UUID
    contract_key: str
    record_type: str
    records_checked: int
    missing_fields: List[Dict[str, Any]]
    unexpected_fields: List[Dict[str, Any]]
    status: str
    drift_score: float


class DataQualityRunRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=10000)


class DataQualityRunResponse(BaseModel):
    job_id: str
    records_seen: int
    records_cleaned: int
    records_failed: int
    checks_passed: int
    checks_warned: int
    checks_failed: int
    contracts_created_or_used: List[str]


class DataQualitySummaryResponse(BaseModel):
    job_id: str
    checks: Dict[str, int]
    cleaned_records: Dict[str, int]
    average_quality_score: Optional[float]


class DataQualityCheckResponse(BaseModel):
    check_id: UUID
    job_id: UUID
    source_id: Optional[UUID]
    raw_record_id: Optional[UUID]
    contract_id: Optional[UUID]
    rule_id: Optional[UUID]
    check_scope: str
    status: str
    severity: str
    message: str
    observed_value: Dict[str, Any]
    check_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class QualityFailureReportResponse(BaseModel):
    job_id: UUID
    total_failures: int
    total_warnings: int
    failure_groups: List[Dict[str, Any]]
    warning_groups: List[Dict[str, Any]]
    sample_failures: List[DataQualityCheckResponse]


class CleanedIngestionRecordResponse(BaseModel):
    cleaned_record_id: UUID
    raw_record_id: UUID
    job_id: UUID
    source_id: Optional[UUID]
    source_key: Optional[str] = None
    source_name: Optional[str] = None
    tenant_id: Optional[UUID] = None
    contract_id: Optional[UUID]
    normaliser_definition_id: Optional[UUID] = None
    normaliser_key: Optional[str] = None
    normaliser_version: Optional[str] = None
    cleaning_status: str
    content_hash: str
    quality_score: float
    cleaned_payload: Dict[str, Any]
    cleaning_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RejectedRecordReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(valid|approved|rejected|skipped|noise|corrected|pending)$")
    note: Optional[str] = None
    corrected_payload: Optional[Dict[str, Any]] = None


class RejectedRecordReviewResponse(BaseModel):
    record_id: UUID
    validation_status: str
    normalised_payload: Dict[str, Any]
    review_metadata: Dict[str, Any]


class IngestionJobDetailResponse(BaseModel):
    job: IngestionJobResponse
    records: List[RawRecordResponse]
    lineage: List[LineageEventResponse]
