"""
Schemas for skills and ESCO harmonisation APIs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


ORM_CONFIG = ConfigDict(from_attributes=True)


class SkillResponse(BaseModel):
    skill_id: UUID
    skill_key: str
    name: str
    category: Optional[str]
    description: Optional[str]
    status: str
    skill_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class SkillMappingResponse(BaseModel):
    mapping_id: UUID
    skill_id: UUID
    esco_skill_id: Optional[UUID]
    source_domain: str
    source_entity_type: str
    source_entity_id: Optional[UUID]
    source_record_id: Optional[str]
    source_text_hash: Optional[str]
    matched_text: str
    extraction_method: str
    confidence_score: float
    evidence_start: Optional[int]
    evidence_end: Optional[int]
    evidence_text: Optional[str]
    mapping_status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None
    confidence_calibration: Dict[str, Any] = Field(default_factory=dict)
    mapping_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class SkillSummaryResponse(BaseModel):
    skills: int
    esco_skills: int
    aliases: int
    mappings: int
    curriculum_mappings: int
    labour_market_mappings: int
    skill_demand_evidence: int = 0
    candidate_mappings: int = 0
    approved_mappings: int = 0
    rejected_mappings: int = 0


class ESCOSkillResponse(BaseModel):
    esco_skill_id: UUID
    skill_id: Optional[UUID]
    esco_uri: Optional[str]
    preferred_label: str
    skill_type: Optional[str]
    reuse_level: Optional[str]
    description: Optional[str]
    taxonomy_version: str
    esco_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class SkillAliasResponse(BaseModel):
    alias_id: UUID
    skill_id: UUID
    alias: str
    normalised_alias: str
    language: str
    source: str
    confidence_weight: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class SkillAliasCreateRequest(BaseModel):
    skill_id: UUID
    alias: str = Field(..., min_length=1, max_length=255)
    language: str = Field(default="en", min_length=1, max_length=20)
    source: str = Field(default="manual", min_length=1, max_length=100)
    confidence_weight: float = Field(default=1.0, ge=0.0, le=1.0)


class SkillAliasUpdateRequest(BaseModel):
    alias: Optional[str] = Field(default=None, min_length=1, max_length=255)
    language: Optional[str] = Field(default=None, min_length=1, max_length=20)
    source: Optional[str] = Field(default=None, min_length=1, max_length=100)
    confidence_weight: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    is_active: Optional[bool] = None


class ESCOImportResponse(BaseModel):
    records_seen: int
    skills_created: int
    esco_created: int
    esco_updated: int
    aliases_created: int
    dry_run: bool = False
    valid_records: Optional[int] = None
    issues: List[Dict[str, Any]] = Field(default_factory=list)
    sample_records: List[Dict[str, Any]] = Field(default_factory=list)


class SemanticSkillMatchRequest(BaseModel):
    text: str = Field(..., min_length=1)
    threshold: float = Field(default=0.40, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=100)


class SemanticSkillMatchResponse(BaseModel):
    skill_id: UUID
    skill_key: str
    name: str
    confidence_score: float
    semantic_similarity: float
    confidence_calibration: Dict[str, Any]
    matched_text: str


class SkillMappingReviewRequest(BaseModel):
    decision: str = Field(
        default="approved",
        pattern="^(approved|rejected|merged|needs_review|deferred|disagreement|resolved)$",
    )
    note: Optional[str] = None
    skill_id: Optional[UUID] = None


class AlignmentCalibrationRequest(BaseModel):
    expert_alignment_score: float = Field(..., ge=0.0, le=1.0)
    note: Optional[str] = None


class SkillMergeRequest(BaseModel):
    source_skill_id: UUID
    target_skill_id: UUID
    note: Optional[str] = None


class SkillMergeResponse(BaseModel):
    source_skill_id: str
    target_skill_id: str
    aliases_moved: int
    mappings_moved: int
    esco_records_moved: int
    evidence_moved: int = 0
    signals_superseded: int = 0


class SkillDuplicateCandidateResponse(BaseModel):
    source_skill_id: UUID
    source_skill_key: str
    source_name: str
    target_skill_id: UUID
    target_skill_key: str
    target_name: str
    score: float
    reasons: List[str]
    source_mapping_count: int
    target_mapping_count: int
    recommendation: str


class SkillDuplicateMergeRequest(BaseModel):
    source_skill_id: UUID
    target_skill_id: UUID
    note: Optional[str] = None


class CurriculumSkillExtractionRequest(BaseModel):
    version_id: Optional[UUID] = None
    limit: int = Field(default=1000, ge=1, le=10000)


class LabourMarketSkillExtractionRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=10000)


class SkillExtractionResponse(BaseModel):
    source_domain: str
    records_seen: int
    mappings_created: int
    mappings_skipped: int


class SkillDemandEvidenceGenerateRequest(BaseModel):
    limit: int = Field(default=10000, ge=1, le=100000)


class SkillDemandEvidenceGenerateResponse(BaseModel):
    signals_seen: int
    skills_seen: int
    evidence_seen: int
    evidence_created: int
    evidence_skipped: int


class SkillDemandEvidenceResponse(BaseModel):
    evidence_id: UUID
    skill_id: UUID
    signal_id: UUID
    evidence_type: str
    match_method: str
    matched_context: str
    demand_score: float
    confidence_score: float
    evidence_weight: float
    rationale: Optional[str]
    evidence_hash: str
    evidence_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ESCOOccupationResponse(BaseModel):
    esco_occupation_id: UUID
    esco_uri: Optional[str]
    preferred_label: str
    code: Optional[str]
    description: Optional[str]
    status: Optional[str]
    taxonomy_version: str
    parent_id: Optional[UUID]
    broader_occupation_uri: Optional[str]
    top_concept: bool
    occupation_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ESCOOccupationSkillLinkResponse(BaseModel):
    link_id: UUID
    occupation_id: UUID
    skill_id: UUID
    relationship_type: str
    skill_type: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ESCOOccupationDetailResponse(ESCOOccupationResponse):
    essential_skills: List[ESCOOccupationSkillLinkResponse] = Field(default_factory=list)
    children: List[ESCOOccupationResponse] = Field(default_factory=list)


class ESCOOccupationImportResponse(BaseModel):
    records_seen: int
    occupations_created: int
    occupations_updated: int
    skill_links_created: int


class ESCOCrosswalkItem(BaseModel):
    skill_id: UUID
    skill_key: str
    skill_name: str
    esco_skill_id: Optional[UUID] = None
    esco_preferred_label: Optional[str] = None
    esco_uri: Optional[str] = None
    curriculum_modules: List[str] = Field(default_factory=list)
    mapping_count: int = 0

    model_config = ORM_CONFIG


class ESCOCrosswalkResponse(BaseModel):
    total_curriculum_skills: int
    covered_by_esco: int
    not_covered_by_esco: int
    esco_coverage_pct: float
    items: List[ESCOCrosswalkItem] = Field(default_factory=list)
    top_esco_skills: List[Dict[str, Any]] = Field(default_factory=list)
    missing_skill_keys: List[str] = Field(default_factory=list)
