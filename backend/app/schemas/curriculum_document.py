"""
Schemas for curriculum document ingestion APIs.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.ingestion import IngestionJobResponse


ORM_CONFIG = ConfigDict(from_attributes=True)


class CurriculumDocumentResponse(BaseModel):
    document_id: UUID
    document_key: str
    tenant_id: Optional[UUID] = None
    faculty_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    programme_id: Optional[UUID] = None
    title: str
    faculty: Optional[str]
    department: Optional[str]
    programme: Optional[str]
    status: str
    current_version_number: int
    description: Optional[str]
    document_metadata: Dict[str, Any]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class CurriculumDocumentVersionResponse(BaseModel):
    version_id: UUID
    document_id: UUID
    job_id: Optional[UUID]
    source_id: Optional[UUID]
    tenant_id: Optional[UUID] = None
    raw_record_id: Optional[UUID]
    version_number: int
    original_filename: str
    storage_uri: str
    content_hash: str
    mime_type: Optional[str]
    file_size: int
    extracted_text_hash: Optional[str]
    page_count: int
    chunk_count: int
    extraction_status: str
    extraction_metadata: Dict[str, Any]
    uploaded_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class DocumentChunkResponse(BaseModel):
    chunk_id: UUID
    version_id: UUID
    job_id: Optional[UUID]
    raw_record_id: Optional[UUID]
    module_id: Optional[UUID] = None
    programme_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    chunk_index: int
    page_start: Optional[int]
    page_end: Optional[int]
    char_start: int
    char_end: int
    content: str
    content_hash: str
    token_count: int
    chunk_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class CurriculumDocumentDetailResponse(BaseModel):
    document: CurriculumDocumentResponse
    versions: List[CurriculumDocumentVersionResponse]


class CurriculumUploadResponse(BaseModel):
    message: str
    document: Optional[CurriculumDocumentResponse] = None
    version: Optional[CurriculumDocumentVersionResponse] = None
    job: Optional[IngestionJobResponse] = None
    chunk_count: int = 0
    operational_job: Optional[Dict[str, Any]] = None


class CurriculumApiImportRequest(BaseModel):
    endpoint_url: str
    title: Optional[str] = None
    faculty: Optional[str] = None
    department: Optional[str] = None
    programme: Optional[str] = None
    document_key: Optional[str] = None
    description: Optional[str] = None
    requires_credentials: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    response_format: str = "auto"


class CurriculumDiscoveryRequest(BaseModel):
    start_url: str
    institution: Optional[str] = None
    max_links: int = Field(default=50, ge=1, le=250)
    same_domain_only: bool = True


class CurriculumDiscoveryCandidate(BaseModel):
    url: str
    title: str
    source_format: str
    document_type: str
    confidence_score: float
    reason: str


class CurriculumDiscoveryResponse(BaseModel):
    start_url: str
    institution: Optional[str]
    page_title: Optional[str]
    candidates: List[CurriculumDiscoveryCandidate]
    total_candidates: int


class CPUTProspectusImportRequest(BaseModel):
    faculty_code: str = "220"
    max_courses: Optional[int] = 5
    course_codes: Optional[List[str]] = None


class CPUTProspectusImportResponse(BaseModel):
    message: str
    job: Optional[IngestionJobResponse] = None
    faculty_code: str
    courses_discovered: int = 0
    programmes_imported: int = 0
    modules_imported: int = 0
    failed_courses: int = 0
    operational_job: Optional[Dict[str, Any]] = None


class AcademicFacultyResponse(BaseModel):
    faculty_id: UUID
    faculty_key: str
    name: str
    description: Optional[str]
    status: str
    faculty_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class AcademicDepartmentResponse(BaseModel):
    department_id: UUID
    faculty_id: Optional[UUID]
    department_key: str
    name: str
    description: Optional[str]
    status: str
    department_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class AcademicProgrammeResponse(BaseModel):
    programme_id: UUID
    department_id: Optional[UUID]
    programme_key: str
    name: str
    qualification_type: Optional[str]
    nqf_level: Optional[str]
    description: Optional[str]
    status: str
    programme_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG



class CurriculumModuleResponse(BaseModel):
    module_id: UUID
    module_code: str
    module_name: str
    programme_id: Optional[UUID] = None
    description: Optional[str] = None
    nqf_level: Optional[int] = None
    faculty: Optional[str] = None
    programme: Optional[str] = None
    credits: Optional[int] = None
    is_active: bool
    data_source: Optional[str] = None
    last_processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG

class CurriculumHierarchyResponse(BaseModel):
    faculties: List[AcademicFacultyResponse]
    departments: List[AcademicDepartmentResponse]
    programmes: List[AcademicProgrammeResponse]
    modules: List[CurriculumModuleResponse] = Field(default_factory=list)


class CurriculumVersionComparisonResponse(BaseModel):
    document_id: UUID
    from_version_id: UUID
    to_version_id: UUID
    from_version_number: int
    to_version_number: int
    chunk_count_delta: int
    added_chunk_hashes: List[str]
    removed_chunk_hashes: List[str]
    shared_chunk_hash_count: int
    section_changes: Dict[str, Any]
    outcome_type_changes: Dict[str, Any]
    module_changes: Dict[str, Any]
    skill_coverage_changes: Dict[str, Any]
    text_diff: List[str]


class CurriculumEvidenceReviewRequest(BaseModel):
    decision: str = Field(pattern="^(validated|changes_required|rejected)$")
    source_authoritative: bool
    extraction_complete: bool
    module_evidence_complete: bool
    learning_outcomes_complete: bool
    completeness_score: int = Field(ge=0, le=100)
    issue_codes: List[str] = Field(default_factory=list)
    notes: str = Field(min_length=10, max_length=5000)


class CurriculumGovernanceEvidenceCreate(BaseModel):
    layer: str = Field(pattern="^(legislation|nqf|heqsf|che_standard|che_accreditation|dhet_pqm|saqa_registration|institutional_programme|module_curriculum)$")
    authority: str = Field(min_length=2, max_length=120)
    evidence_key: str = Field(min_length=3, max_length=180, pattern="^[a-zA-Z0-9_.:-]+$")
    title: str = Field(min_length=3, max_length=500)
    identifier: Optional[str] = Field(default=None, max_length=150)
    version_label: Optional[str] = Field(default=None, max_length=100)
    official_url: Optional[str] = Field(default=None, max_length=1000)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    currency_status: str = Field(default="unverified", pattern="^(current|historical|expired|unknown|unverified)$")
    verification_status: str = Field(default="unverified", pattern="^(unverified|verified|changes_required|rejected)$")
    nqf_level: Optional[int] = Field(default=None, ge=1, le=10)
    credits: Optional[int] = Field(default=None, ge=0, le=1000)
    notes: Optional[str] = Field(default=None, max_length=5000)
    parent_evidence_id: Optional[UUID] = None
    programme_id: Optional[UUID] = None
    document_version_id: Optional[UUID] = None
    evidence_metadata: Dict[str, Any] = Field(default_factory=dict)


