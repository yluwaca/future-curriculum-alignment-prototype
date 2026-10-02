"""
Schemas for analytics and recommendation APIs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.schemas.skills import SkillDemandEvidenceResponse, SkillResponse


ORM_CONFIG = ConfigDict(from_attributes=True, protected_namespaces=())

ALLOWED_REVIEW_PRIORITIES = {"high", "medium", "low"}
ALLOWED_REVIEW_DECISIONS = {"approve", "reject", "modify"}


class GenerateAnalyticsRequest(BaseModel):
    version_id: Optional[UUID] = None
    horizon_periods: int = Field(default=4, ge=1, le=24)


class GenerateAnalyticsResponse(BaseModel):
    alignments_created: int
    forecasts_created: int
    recommendations_created: int
    recommendations_superseded: int = 0


class AnalyticsSummaryResponse(BaseModel):
    alignment_scores: int
    forecasts: int
    recommendations: int
    labour_market_signals: int = 0
    skill_demand_evidence: int = 0
    recommendation_explanations: int


class AlignmentScoreResponse(BaseModel):
    alignment_id: UUID
    document_id: Optional[UUID]
    version_id: Optional[UUID]
    score_type: str
    alignment_score: float
    gap_score: float
    curriculum_skill_count: int
    labour_market_skill_count: int
    overlapping_skill_count: int
    missing_skill_count: int
    confidence_score: float
    model_version: str
    status: str
    score_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class ForecastResponse(BaseModel):
    forecast_id: UUID
    skill_id: Optional[UUID]
    skill_name: Optional[str] = None
    skill_key: Optional[str] = None
    forecast_type: str
    horizon_periods: int
    baseline_value: float
    forecast_value: float
    trend_direction: str
    confidence_score: float
    method: str
    forecast_payload: Dict[str, Any]
    explanation: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RecommendationExplanationResponse(BaseModel):
    explanation_id: UUID
    recommendation_id: UUID
    explanation_type: str
    explanation_text: str
    evidence: Dict[str, Any]
    confidence_score: float
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RecommendationResponse(BaseModel):
    recommendation_id: UUID
    alignment_id: Optional[UUID]
    forecast_id: Optional[UUID]
    skill_id: Optional[UUID]
    document_id: Optional[UUID]
    version_id: Optional[UUID]
    recommendation_type: str
    title: str
    description: str
    priority: str
    priority_score: float
    confidence_score: float
    status: str
    recommendation_metadata: Dict[str, Any]
    actionable: Optional[bool] = None
    non_actionable_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RecommendationReviewRequest(BaseModel):
    reason: Optional[str] = None
    feedback_comment: Optional[str] = None
    feedback_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    modified_title: Optional[str] = None
    modified_description: Optional[str] = None
    modified_priority: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    recommendation_id: Optional[UUID] = None
    decision: Optional[str] = None
    evidence_reviewed: Optional[bool] = None
    evidence_context: Optional[Dict[str, Any]] = None

    @field_validator("reason", "feedback_comment", "modified_title", "modified_description")
    @classmethod
    def _normalise_review_text(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            return None
        field = info.field_name
        if field == "modified_title":
            if len(stripped) > 255:
                raise ValueError("modified_title must be at most 255 characters")
        elif field in ("reason", "feedback_comment"):
            if len(stripped) > 4000:
                raise ValueError(f"{field} must be at most 4000 characters")
        return stripped

    @field_validator("modified_priority")
    @classmethod
    def _validate_modified_priority(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalised = str(value).strip().lower()
        if normalised not in ALLOWED_REVIEW_PRIORITIES:
            raise ValueError("modified_priority must be one of: high, medium, low")
        return normalised

    @field_validator("decision")
    @classmethod
    def _validate_decision(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalised = str(value).strip().lower()
        if normalised not in ALLOWED_REVIEW_DECISIONS:
            raise ValueError("decision must be one of: approve, reject, modify")
        return normalised


class RecommendationReviewResponse(BaseModel):
    review_id: UUID
    recommendation_id: UUID
    reviewer_id: Optional[str]
    decision: str
    previous_status: str
    new_status: str
    decision_reason: Optional[str]
    confidence_score: Optional[float]
    modified_title: Optional[str]
    modified_description: Optional[str]
    modified_priority: Optional[str]
    review_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class CommitteeDecisionRequest(BaseModel):
    evidence_report_id: UUID
    decision: str
    rationale: str = Field(..., min_length=10)
    committee_name: str = Field(..., min_length=2)
    meeting_reference: str = Field(..., min_length=2)
    conditions: Optional[str] = None


class RecommendationFeedbackRequest(BaseModel):
    feedback_type: str = "review_comment"
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    comment: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RecommendationFeedbackResponse(BaseModel):
    feedback_id: UUID
    recommendation_id: UUID
    review_id: Optional[UUID]
    reviewer_id: Optional[str]
    feedback_type: str
    rating: Optional[float]
    comment: str
    feedback_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RecommendationStatusHistoryResponse(BaseModel):
    history_id: UUID
    recommendation_id: UUID
    changed_by: Optional[str]
    previous_status: Optional[str]
    new_status: str
    change_reason: Optional[str]
    transition_type: str
    history_metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class RecommendationDossierResponse(BaseModel):
    recommendation: RecommendationResponse
    skill: Optional[SkillResponse] = None
    alignment: Optional[AlignmentScoreResponse] = None
    forecast: Optional[ForecastResponse] = None
    explanations: List[RecommendationExplanationResponse]
    demand_evidence: List[SkillDemandEvidenceResponse]
    reviews: List[RecommendationReviewResponse]
    feedback: List[RecommendationFeedbackResponse]
    status_history: List[RecommendationStatusHistoryResponse]
    evidence_summary: Dict[str, Any]
    actionable: Optional[bool] = None
    non_actionable_reason: Optional[str] = None


class GeneratedReportResponse(BaseModel):
    report_id: UUID
    report_type: str
    source_entity_type: str
    source_entity_id: Optional[UUID]
    generated_by: Optional[str]
    status: str
    title: str
    summary: Dict[str, Any]
    payload_hash: str
    format_hint: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ORM_CONFIG


class GeneratedReportDetailResponse(GeneratedReportResponse):
    payload: Dict[str, Any]


class RecommendationLineageResponse(BaseModel):
    recommendation_id: UUID
    skill_id: Optional[UUID]
    lineage_nodes: List[Dict[str, Any]]
    lineage_edges: List[Dict[str, Any]]
    lineage_events: List[Dict[str, Any]]
    summary: Dict[str, Any]
