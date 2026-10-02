# backend/app/schemas/predictive.py

"""
Predictive analytics schemas.

Provides:
- ETL ingestion schemas
- curriculum schemas
- job posting schemas
- predictive output schemas
- alignment prediction schemas
- forecasting schemas
- SHAP explainability schemas
- analytics/status schemas

Aligned with:
- PostgreSQL schema
- SQLAlchemy models
- Pydantic v2
- FastAPI OpenAPI
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


# =========================================================
# Base Configuration
# =========================================================

ORM_CONFIG = ConfigDict(
    from_attributes=True,
    protected_namespaces=(),
)

MODEL_CONFIG = ConfigDict(
    protected_namespaces=(),
)


# =========================================================
# Curriculum Module Schemas
# =========================================================

class CurriculumModuleBase(BaseModel):
    """
    Shared curriculum module fields.
    """

    module_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    module_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    description: Optional[str] = None

    nqf_level: Optional[int] = Field(
        None,
        ge=1,
        le=10,
    )

    faculty: Optional[str] = Field(
        None,
        max_length=100,
    )

    programme: Optional[str] = Field(
        None,
        max_length=150,
    )

    credits: Optional[int] = Field(
        None,
        ge=0,
        le=999,
    )

    data_source: Optional[str] = Field(
        default="Internal",
        max_length=100,
    )

    is_active: bool = True


class CurriculumModuleCreate(
    CurriculumModuleBase
):
    """
    Curriculum module creation schema.
    """


class CurriculumModuleUpdate(BaseModel):
    """
    Curriculum module partial update schema.
    """

    module_name: Optional[str] = None

    description: Optional[str] = None

    nqf_level: Optional[int] = Field(
        None,
        ge=1,
        le=10,
    )

    faculty: Optional[str] = None

    programme: Optional[str] = None

    credits: Optional[int] = None

    is_active: Optional[bool] = None

    data_source: Optional[str] = None

    model_config = ConfigDict(
        extra="forbid",
    )


class CurriculumModuleResponse(
    CurriculumModuleBase
):
    """
    Curriculum module API response.
    """

    module_id: UUID

    created_at: datetime

    updated_at: datetime

    last_processed_at: Optional[datetime]

    model_config = ORM_CONFIG


# =========================================================
# Job Posting Schemas
# =========================================================

class JobPostingBase(BaseModel):
    """
    Shared job posting fields.
    """

    job_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    job_title: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    job_description: Optional[str] = None

    required_skills: Optional[
        List[str]
    ] = None

    education_level: Optional[str] = None

    experience_years: Optional[int] = Field(
        None,
        ge=0,
        le=50,
    )

    region: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    country: str = Field(
        default="ZA",
        max_length=2,
    )

    employment_type: Optional[str] = None

    salary_min: Optional[Decimal] = Field(
        None,
        ge=0,
    )

    salary_max: Optional[Decimal] = Field(
        None,
        ge=0,
    )

    posted_date: datetime

    closed_date: Optional[datetime] = None

    posting_year: int

    posting_month: int = Field(
        ...,
        ge=1,
        le=12,
    )

    posting_quarter: int = Field(
        ...,
        ge=1,
        le=4,
    )

    source: Optional[str] = None

    source_url: Optional[str] = None

    is_processed: bool = False

    embedding_generated: bool = False


class JobPostingCreate(
    JobPostingBase
):
    """
    Job posting creation schema.
    """


class JobPostingUpdate(BaseModel):
    """
    Job posting partial update schema.
    """

    job_title: Optional[str] = None

    job_description: Optional[str] = None

    required_skills: Optional[
        List[str]
    ] = None

    education_level: Optional[str] = None

    experience_years: Optional[int] = None

    region: Optional[str] = None

    employment_type: Optional[str] = None

    salary_min: Optional[Decimal] = None

    salary_max: Optional[Decimal] = None

    closed_date: Optional[datetime] = None

    source: Optional[str] = None

    source_url: Optional[str] = None

    is_processed: Optional[bool] = None

    embedding_generated: Optional[bool] = None

    model_config = ConfigDict(
        extra="forbid",
    )


class JobPostingResponse(
    JobPostingBase
):
    """
    Job posting API response.
    """

    posting_id: UUID

    created_at: datetime

    updated_at: datetime

    last_processed_at: Optional[
        datetime
    ]

    model_config = ORM_CONFIG


# =========================================================
# SHAP Explainability Schemas
# =========================================================

class SHAPFeatureImpact(BaseModel):
    """
    Single SHAP feature contribution.
    """

    feature_name: str

    shap_value: float

    feature_value: Optional[float] = None


# =========================================================
# Predictive Output Schemas
# =========================================================

class PredictiveOutputBase(BaseModel):
    """
    Shared predictive output fields.
    """

    curriculum_module_code: str

    curriculum_nqf_level: Optional[int]

    faculty: Optional[str]

    model_type: str

    model_version: Optional[str]

    alignment_score: Optional[
        Decimal
    ]

    is_aligned: Optional[bool]

    confidence_score: Optional[
        Decimal
    ]

    gap_score: Optional[
        Decimal
    ]

    gap_flag: bool = False

    forecast_horizon_months: Optional[
        int
    ]

    forecast_data: Optional[
        Dict[str, Any]
    ]

    forecast_rmse: Optional[
        Decimal
    ]

    forecast_mape: Optional[
        Decimal
    ]

    shap_summary: Optional[
        List[SHAPFeatureImpact]
    ]

    shap_full_values: Optional[
        Dict[str, Any]
    ]

    top_influencing_skills: Optional[
        List[Dict[str, Any]]
    ]

    data_region: Optional[str]

    input_features_hash: Optional[str]

    inference_duration_ms: Optional[
        int
    ]

    dataset_version: Optional[str]

    model_config = MODEL_CONFIG


class PredictiveOutputCreate(
    PredictiveOutputBase
):
    """
    Predictive output creation schema.
    """


class PredictiveOutputResponse(
    PredictiveOutputBase
):
    """
    Predictive output API response.
    """

    prediction_id: UUID

    prediction_timestamp: datetime

    created_at: datetime

    updated_at: datetime

    model_config = ORM_CONFIG


# =========================================================
# ETL Batch Schemas
# =========================================================

class IngestRequest(BaseModel):
    """
    Batch ETL ingestion request.
    """

    curriculum_data: Optional[
        List[CurriculumModuleCreate]
    ] = None

    job_posting_data: Optional[
        List[JobPostingCreate]
    ] = None

    force_reprocess: bool = False


class IngestResponse(BaseModel):
    """
    ETL ingestion response.
    """

    message: str

    curriculum_ingested: int

    job_postings_ingested: int

    timestamp: datetime


# =========================================================
# Alignment Prediction Schemas
# =========================================================

class AlignmentRequest(BaseModel):
    """
    Curriculum-demand alignment request.
    """

    module_code: str = Field(
        ...,
        min_length=1,
        max_length=50,
    )

    region: Optional[str] = None


class AlignmentResponse(BaseModel):
    """
    Alignment prediction response.
    """

    prediction_id: UUID

    module_code: str

    alignment_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
    )

    is_aligned: bool

    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
    )

    gap_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
    )

    gap_flag: bool

    shap_summary: Optional[
        List[SHAPFeatureImpact]
    ]

    top_influencing_skills: Optional[
        List[Dict[str, Any]]
    ]

    prediction_timestamp: datetime

    model_version: Optional[str]

    dataset_version: Optional[str]

    model_config = MODEL_CONFIG


# =========================================================
# Forecast Schemas
# =========================================================

class ForecastRequest(BaseModel):
    """
    Demand forecasting request.
    """

    module_code: str

    forecast_horizon: int = Field(
        default=12,
        ge=1,
        le=36,
    )

    region: Optional[str] = None


class ForecastDataPoint(BaseModel):
    """
    Forecast trajectory point.
    """

    month: int = Field(
        ...,
        ge=1,
        le=36,
    )

    predicted_demand: float = Field(
        ...,
        ge=0.0,
    )

    confidence_lower: Optional[
        float
    ] = None

    confidence_upper: Optional[
        float
    ] = None


class ForecastResponse(BaseModel):
    """
    Forecasting response payload.
    """

    prediction_id: UUID

    module_code: str

    forecast_horizon_months: int

    forecast_trajectory: List[
        ForecastDataPoint
    ]

    rmse: Optional[float]

    mape: Optional[float]

    prediction_timestamp: datetime

    model_version: Optional[str]

    dataset_version: Optional[str]

    data_region: Optional[str]

    model_config = MODEL_CONFIG


# =========================================================
# Analytics / Status Schemas
# =========================================================

class ModelMetrics(BaseModel):
    """
    Model performance metrics.
    """

    f1_score: Optional[float] = None

    roc_auc: Optional[float] = None

    rmse: Optional[float] = None

    mape: Optional[float] = None

    model_config = MODEL_CONFIG


class StatusResponse(BaseModel):
    """
    Predictive platform status response.
    """

    xgboost_model_loaded: bool

    lstm_model_loaded: bool

    xgboost_last_trained: Optional[
        datetime
    ]

    lstm_last_trained: Optional[
        datetime
    ]

    xgboost_metrics: Optional[
        ModelMetrics
    ]

    lstm_metrics: Optional[
        ModelMetrics
    ]

    total_curriculum_records: int

    total_job_postings: int

    last_etl_run: Optional[datetime]

    message: str
