"""
Dynamic ingestion API endpoints.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import mimetypes
from pathlib import Path
import re

log = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
import requests
import os
from pydantic import BaseModel, Field
from app.models.job_posting import JobPosting
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.core.tenant_scope import (
    assert_entity_access,
    enforce_requested_tenant,
    scope_query,
)
from app.db.session import get_db
from app.models.data_lineage_event import DataLineageEvent
from app.models.cleaned_ingestion_record import CleanedIngestionRecord
from app.models.connector_definition import ConnectorDefinition
from app.models.data_quality_check import DataQualityCheck
from app.models.data_source import DataSource
from app.models.extracted_table import ExtractedTable
from app.models.extracted_table_row import ExtractedTableRow
from app.models.ingestion_contract import IngestionContract
from app.models.ingestion_failure_event import IngestionFailureEvent
from app.models.ingestion_job import IngestionJob
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.models.normaliser_definition import NormaliserDefinition
from app.models.raw_ingestion_record import RawIngestionRecord
from app.models.user import User
from app.schemas.ingestion import (
    CleanedIngestionRecordResponse,
    ConnectorDefinitionCreate,
    ConnectorDefinitionResponse,
    ConnectorDefinitionUpdate,
    ConnectorHealthResponse,
    ConnectorScheduleResponse,
    ConnectorScheduleUpdate,
    ContractCloneRequest,
    ContractDriftReportResponse,
    CHEVitalStatsJobRequest,
    CredentialSaveRequest,
    CredentialStatusResponse,
    CredentialTestRequest,
    DataSourceCreate,
    DataSourceResponse,
    DataSourceUpdate,
    DataQualityCheckResponse,
    DataQualityRunRequest,
    DataQualityRunResponse,
    DataQualitySummaryResponse,
    ExtractedTableResponse,
    ExtractedTableRowResponse,
    IngestionContractResponse,
    IngestionContractUpdate,
    IngestionFailureEventResponse,
    IngestionJobDetailResponse,
    IngestionJobResponse,
    IngestionRetryResponse,
    JobBoardSimulationRequest,
    JobBoardSimulationResponse,
    NormaliserDefinitionResponse,
    QualityFailureReportResponse,
    RawRecordResponse,
    RejectedRecordReviewRequest,
    RejectedRecordReviewResponse,
    SourceFreshnessResponse,
    SourceClassificationResponse,
    SourceFileArchiveResponse,
    DueScheduleResponse,
    StatsSAJobRequest,
    StatsSAJobStartResponse,
)
from app.services.audit_service import log_audit_event
from app.services.ingestion.connector_registry_service import connector_registry_service
from app.services.ingestion.che_vitalstats_connector import CHEVitalStatsConnector
from app.services.ingestion.data_quality_service import data_quality_service
from app.services.ingestion.credential_service import credential_service
from app.services.ingestion.adzuna_paginated_importer import (
    AdzunaPaginationError,
    adzuna_paginated_importer,
    provider_spec,
)
from app.services.ingestion.job_board_api_connector import job_board_api_connector
from app.services.ingestion.job_service import ingestion_job_service
from app.services.ingestion.normaliser_registry_service import normaliser_registry_service
from app.services.ingestion.statssa_connector import StatsSAQLFSConnector
from app.services.operational_job_service import operational_job_service
from app.services.production_data_quality_service import production_data_quality_service


router = APIRouter(
    prefix="/ingestion",
    tags=["ingestion"],
)


class AdzunaImportRequest(BaseModel):
    what: str = Field(default="software developer", min_length=1, max_length=120)
    where: str = Field(default="Cape Town", min_length=1, max_length=120)
    limit: int = Field(default=5, ge=1, le=50)


class AdzunaPagesRequest(BaseModel):
    what: str = Field(default="developer", min_length=1, max_length=120)
    where: str = Field(default="South Africa", max_length=120)
    page_size: int = Field(default=50, ge=1, le=50)
    page_start: int = Field(default=1, ge=1, le=250)
    page_end: Optional[int] = Field(default=None, ge=1, le=250)
    date_from: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sort_by: str = Field(default="date", pattern=r"^(date|relevance|salary|default|hybrid)$")
    sort_direction: str = Field(default="down", pattern=r"^(up|down)$")
    requests_per_minute: int = Field(default=30, ge=1, le=120)


@router.post("/adzuna/import")
def import_adzuna(
    payload: AdzunaImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    source = db.query(DataSource).filter(DataSource.source_key == "adzuna_jobs_api_trial").first()
    saved = credential_service.decrypt_config(source.auth_config or {}) if source else {}
    app_id = os.getenv("ADZUNA_APP_ID") or saved.get("app_id")
    app_key = os.getenv("ADZUNA_APP_KEY") or saved.get("api_key")
    if not app_id or not app_key:
        raise HTTPException(503, "Adzuna credentials are not configured on the server.")
    try:
        response = requests.get(
            "https://api.adzuna.com/v1/api/jobs/za/search/1",
            params={"app_id": app_id, "app_key": app_key, "what": payload.what,
                    "where": payload.where, "results_per_page": payload.limit},
            timeout=30,
        )
    except requests.RequestException:
        raise HTTPException(502, "Adzuna could not be reached. Please retry later.") from None
    if response.status_code != 200:
        raise HTTPException(502, f"Adzuna returned HTTP {response.status_code}. Check account access or quota.")
    try:
        body = response.json()
        rows = body["results"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, "Adzuna returned an unexpected response format.") from None
    result = job_board_api_connector.ingest_payloads(
        db, "adzuna", rows[:payload.limit], current_user.identity_id,
source_label="ADZUNA_TRIAL_NOT_EMPIRICAL", acquisition_mode="live_trial_uat",
    )
    job = db.get(IngestionJob, UUID(result["job_id"]))
    job.parameters = {**job.parameters, "query": payload.model_dump(), "initiated_via": "portal"}
    log_audit_event(
        db=db, event_layer="application", event_type="adzuna_import",
        actor_type=current_user.identity_type, actor_id=current_user.identity_id,
        token_id=None, source_component="ingestion.adzuna", action="import_adzuna",
        result="success", metadata=result,
    )
    db.commit()
    return result


@router.post("/adzuna/pages/estimate")
def estimate_adzuna_pages(
    payload: AdzunaPagesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Preview a bounded Adzuna page run without issuing any API request."""
    return adzuna_paginated_importer.estimate(payload)


@router.post("/adzuna/import-pages")
def import_adzuna_pages(
    payload: AdzunaPagesRequest,
    provider: str = Query(default=None, description="Paginated job provider; defaults to FUTURE_PAGINATED_JOB_PROVIDER or adzuna."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Run a bounded, additive page import with server-side limits.

    Provider defaults to the configured active provider (``adzuna`` unless
    ``FUTURE_PAGINATED_JOB_PROVIDER`` is set). Synthetic test-bench imports use
    ``provider=synthetic``, which requires no API credentials and reads its
    search endpoint from ``FUTURE_SYNTHETIC_JOBS_BASE_URL``.
    """
    try:
        config = provider_spec(provider)
    except AdzunaPaginationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from None
    if config["requires_credentials"]:
        source = db.query(DataSource).filter(DataSource.source_key == config["source_key"]).first()
        saved = credential_service.decrypt_config(source.auth_config or {}) if source else {}
        app_id = os.getenv("ADZUNA_APP_ID") or saved.get("app_id")
        app_key = os.getenv("ADZUNA_APP_KEY") or saved.get("api_key")
        credentials = {"app_id": app_id, "api_key": app_key}
    else:
        credentials = {}
    try:
        return adzuna_paginated_importer.import_pages(
            db=db,
            payload=payload,
            actor_type=current_user.identity_type,
            actor_id=current_user.identity_id,
            token_id=None,
            credentials=credentials,
            provider=config["provider"],
        )
    except AdzunaPaginationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from None


@router.get("/adzuna/posts")
def adzuna_posts(
    job_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    provider: str = Query(default=None, description="Paginated job provider whose saved postings are listed."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    try:
        config = provider_spec(provider)
    except AdzunaPaginationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.args[0]) from None
    query = db.query(JobPosting, DataSource).join(DataSource, DataSource.source_id == JobPosting.source_id)
    query = scope_query(query, DataSource, current_user).filter(DataSource.source_key == config["source_key"])
    if job_id:
        run = db.get(IngestionJob, job_id)
        if not run:
            raise HTTPException(404, "Import job not found.")
        assert_entity_access(run, current_user)
        matched_ids = db.query(RawIngestionRecord.source_record_id).filter(
            RawIngestionRecord.job_id == job_id,
            RawIngestionRecord.validation_status.in_(["valid", "duplicate"]),
        )
        query = query.filter((JobPosting.ingestion_job_id == job_id) | JobPosting.job_id.in_(matched_ids))
    total = query.count()
    rows = query.order_by(JobPosting.updated_at.desc(), JobPosting.posting_id).offset(offset).limit(limit).all()
    return {"total": total, "offset": offset, "limit": limit,
            "has_more": offset + len(rows) < total,
            "items": [{"posting_id": str(p.posting_id), "job_id": p.job_id,
            "title": p.job_title, "location": p.region, "posted_date": p.posted_date,
            "description": p.job_description, "url": p.source_url,
            "ingestion_job_id": str(p.ingestion_job_id),
            "source": source.name if source else None} for p, source in rows]}


@router.get("/operations-summary")
def get_operations_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Compact dashboard summary for the Data Operations page.

    This endpoint returns persisted repository counts in one request so the
    portal does not show misleading zeros when detailed catalogue panels are
    unavailable or still loading.
    """

    failed_statuses = {"failed", "error", "invalid", "rejected"}
    failed_quality_statuses = {"fail", "failed", "error"}

    total_quality_checks = db.query(func.count(DataQualityCheck.check_id)).scalar() or 0
    passed_quality_checks = (
        db.query(func.count(DataQualityCheck.check_id))
        .filter(DataQualityCheck.status.in_(["pass", "passed"]))
        .scalar()
        or 0
    )
    failed_checks = (
        db.query(func.count(DataQualityCheck.check_id))
        .filter(DataQualityCheck.status.in_(list(failed_quality_statuses)))
        .scalar()
        or 0
    )
    average_quality = round((passed_quality_checks / total_quality_checks) * 100, 2) if total_quality_checks else None

    return {
        "connector_types": db.query(func.count(ConnectorDefinition.connector_definition_id)).scalar() or 0,
        "normalisers": db.query(func.count(NormaliserDefinition.normaliser_definition_id)).scalar() or 0,
        "education_context": (
            db.query(func.count(DataSource.source_id))
            .filter(DataSource.source_category == "higher_education_context")
            .scalar()
            or 0
        ),
        "contracts": db.query(func.count(IngestionContract.contract_id)).scalar() or 0,
        "cleaned_records": db.query(func.count(CleanedIngestionRecord.cleaned_record_id)).scalar() or 0,
        "labour_trend_facts": db.query(func.count(LabourMarketTrend.trend_id)).scalar() or 0,
        "canonical_signals": db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0,
        "failure_events": db.query(func.count(IngestionFailureEvent.failure_id)).scalar() or 0,
        "failed_checks": failed_checks,
        "average_quality": average_quality,
        "ingestion_jobs": db.query(func.count(IngestionJob.job_id)).scalar() or 0,
        "failed_ingestion_jobs": (
            db.query(func.count(IngestionJob.job_id))
            .filter(IngestionJob.status.in_(list(failed_statuses)))
            .scalar()
            or 0
        ),
    }


def apply_connector_definition_or_fail(
    db: Session,
    source: DataSource,
    connector_definition_id: UUID | None = None,
    connector_key: str | None = None,
) -> None:
    definition = None
    if connector_definition_id:
        definition = connector_registry_service.get_definition_by_id(
            db,
            connector_definition_id,
        )
        if not definition:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Connector definition not found",
            )
    elif connector_key:
        definition = connector_registry_service.get_definition_by_key(
            db,
            connector_key,
        )

    if definition:
        connector_registry_service.apply_definition_to_source(source, definition)




def _slug(value: str, fallback: str = "source") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return (cleaned or fallback)[:80]


def _generic_record_type(source_category: str, source_format: str) -> str:
    category = _slug(source_category, "generic")
    fmt = _slug(source_format, "unknown")
    return f"generic_{category}_{fmt}"[:100]


def _guess_source_format(filename: str | None, content_type: str | None, fallback: str = "unknown") -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    if suffix:
        if suffix == "xlsx":
            return "excel"
        if suffix == "htm":
            return "html"
        return suffix
    guessed = mimetypes.guess_extension(content_type or "") or ""
    guessed = guessed.lower().lstrip(".")
    if guessed:
        return "excel" if guessed == "xlsx" else guessed
    if content_type:
        lowered = content_type.lower()
        if "json" in lowered:
            return "json"
        if "html" in lowered:
            return "html"
        if "csv" in lowered:
            return "csv"
        if "pdf" in lowered:
            return "pdf"
        if "text" in lowered:
            return "txt"
    return fallback


def _safe_text_preview(data: bytes, limit: int = 4000) -> str | None:
    try:
        return data[:limit].decode("utf-8", errors="replace")
    except Exception:
        return None


def _store_generic_payload(*, source_key: str, filename: str, data: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    storage_dir = Path("data") / "generic_intake" / source_key
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename or "payload.bin")[:180]
    storage_path = storage_dir / f"{digest[:16]}_{safe_name}"
    if not storage_path.exists():
        storage_path.write_bytes(data)
    return str(storage_path), digest

def _source_payload(source: DataSource) -> Dict[str, Any]:
    return {
        "source_id": source.source_id,
        "tenant_id": source.tenant_id,
        "connector_definition_id": source.connector_definition_id,
        "source_key": source.source_key,
        "name": source.name,
        "source_type": source.source_type,
        "source_category": source.source_category,
        "connector_type": source.connector_type,
        "source_scope": source.source_scope,
        "ingestion_mode": source.ingestion_mode,
        "source_format": source.source_format,
        "normaliser_key": source.normaliser_key,
        "base_url": source.base_url,
        "storage_path": source.storage_path,
        "refresh_policy": source.refresh_policy,
        "retry_policy": source.retry_policy or {},
        "owner": source.owner,
        "status": source.status,
        "is_authorised": source.is_authorised,
        "config": source.config or {},
        "auth_config": credential_service.mask_config(source.auth_config or {}),
        "last_success_at": source.last_success_at,
        "last_failure_at": source.last_failure_at,
        "consecutive_failures": source.consecutive_failures or 0,
        "circuit_state": source.circuit_state,
        "circuit_open_until": source.circuit_open_until,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


@router.get(
    "/connectors",
    response_model=List[ConnectorDefinitionResponse],
)
def list_connector_definitions(
    source_category: str | None = None,
    ingestion_mode: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return connector_registry_service.list_definitions(
        db=db,
        source_category=source_category,
        ingestion_mode=ingestion_mode,
        active_only=active_only,
    )


@router.post(
    "/connectors",
    response_model=ConnectorDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_connector_definition(
    payload: ConnectorDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    existing = connector_registry_service.get_definition_by_key(db, payload.connector_key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connector definition already exists",
        )
    definition = ConnectorDefinition(**payload.model_dump())
    db.add(definition)
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="connector_definition",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="create_connector_definition",
        result="success",
        metadata={"connector_key": payload.connector_key},
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.get(
    "/connectors/{connector_key}",
    response_model=ConnectorDefinitionResponse,
)
def get_connector_definition(
    connector_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    definition = connector_registry_service.get_definition_by_key(db, connector_key)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector definition not found",
        )
    return definition


@router.put(
    "/connectors/{connector_key}",
    response_model=ConnectorDefinitionResponse,
)
def update_connector_definition(
    connector_key: str,
    payload: ConnectorDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    definition = connector_registry_service.get_definition_by_key(db, connector_key)
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector definition not found",
        )
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(definition, field, value)
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="connector_definition",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="update_connector_definition",
        result="success",
        metadata={"connector_key": connector_key, "updated_fields": sorted(updates.keys())},
    )
    db.commit()
    db.refresh(definition)
    return definition


@router.get(
    "/normalisers",
    response_model=List[NormaliserDefinitionResponse],
)
def list_normaliser_definitions(
    source_category: str | None = None,
    input_format: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return normaliser_registry_service.list_definitions(
        db=db,
        source_category=source_category,
        input_format=input_format,
        active_only=active_only,
    )


@router.get(
    "/normalisers/{normaliser_key}",
    response_model=NormaliserDefinitionResponse,
)
def get_normaliser_definition(
    normaliser_key: str,
    version: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    definition = normaliser_registry_service.get_definition(
        db=db,
        normaliser_key=normaliser_key,
        version=version,
    )
    if not definition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Normaliser definition not found",
        )
    return definition


@router.get(
    "/sources",
    response_model=List[DataSourceResponse],
)
def list_sources(
    tenant_id: UUID | None = None,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    enforce_requested_tenant(current_user, tenant_id)
    query = scope_query(db.query(DataSource), DataSource, current_user, include_shared=include_shared)
    return [_source_payload(source) for source in query.order_by(DataSource.source_category, DataSource.name).all()]


@router.post(
    "/sources",
    response_model=DataSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_source(
    payload: DataSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    existing = (
        db.query(DataSource)
        .filter(DataSource.source_key == payload.source_key)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data source already exists",
        )
    if payload.source_scope == "tenant" and not payload.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tenant-scoped data sources require tenant_id",
        )

    values = payload.model_dump()
    values["tenant_id"] = enforce_requested_tenant(current_user, payload.tenant_id)
    values["source_scope"] = "tenant"
    if values.get("auth_config"):
        values["auth_config"] = credential_service.encrypt_config(values["auth_config"])
    source = DataSource(**values)
    apply_connector_definition_or_fail(
        db=db,
        source=source,
        connector_definition_id=payload.connector_definition_id,
        connector_key=payload.connector_type,
    )
    db.add(source)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="create_data_source",
        result="success",
        metadata={"source_key": payload.source_key},
    )

    db.commit()
    db.refresh(source)
    return _source_payload(source)


@router.get("/sources/known")
def list_known_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    db_names = (
        db.query(DataSource.name, func.count(DataSource.source_id).label("job_count"))
        .filter(DataSource.name.isnot(None), DataSource.name != "")
        .group_by(DataSource.name)
        .order_by(func.count(DataSource.source_id).desc())
        .all()
    )
    hardcoded = [
        "CPUT curriculum",
        "StatsSA QLFS",
        "CHE VitalStats",
        "LMIS/LMAPS",
        "Western Cape OIHD",
        "Indeed",
        "LinkedIn",
        "PNet",
        "CareerJunction",
        "ESCO",
    ]
    seen = set()
    result = []
    for name, count in db_names:
        if name and name not in seen:
            result.append({"name": name, "job_count": count, "source": "db"})
            seen.add(name)
    for name in hardcoded:
        if name not in seen:
            result.append({"name": name, "job_count": 0, "source": "default"})
            seen.add(name)
    result.append({"name": "Other", "job_count": 0, "source": "default"})
    return result


@router.get(
    "/sources/{source_id}",
    response_model=DataSourceResponse,
)
def get_source(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    assert_entity_access(source, current_user)
    return _source_payload(source)


@router.put(
    "/sources/{source_id}",
    response_model=DataSourceResponse,
)
def update_source(
    source_id: UUID,
    payload: DataSourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    assert_entity_access(source, current_user)
    updates = payload.model_dump(exclude_unset=True)
    if "tenant_id" in updates:
        enforce_requested_tenant(current_user, updates["tenant_id"])
    updates["tenant_id"] = current_user.tenant_id
    updates["source_scope"] = "tenant"
    if "auth_config" in updates and updates["auth_config"]:
        updates["auth_config"] = credential_service.encrypt_config(updates["auth_config"])
    for field, value in updates.items():
        setattr(source, field, value)

    if source.source_scope == "tenant" and not source.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Tenant-scoped data sources require tenant_id",
        )

    apply_connector_definition_or_fail(
        db=db,
        source=source,
        connector_definition_id=updates.get("connector_definition_id"),
        connector_key=updates.get("connector_type"),
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="update_data_source",
        result="success",
        metadata={"source_id": str(source_id), "updated_fields": sorted(updates.keys())},
    )

    db.commit()
    db.refresh(source)
    return _source_payload(source)


@router.get(
    "/sources/{source_id}/classification",
    response_model=SourceClassificationResponse,
)
def get_source_classification(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    return connector_registry_service.source_classification(source)


@router.post(
    "/sources/{source_id}/enable",
    response_model=DataSourceResponse,
)
def enable_source(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    source.status = "active"
    source.is_authorised = True
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="enable_data_source",
        result="success",
        metadata={"source_id": str(source_id), "source_key": source.source_key},
    )
    db.commit()
    db.refresh(source)
    return _source_payload(source)


@router.post(
    "/sources/{source_id}/disable",
    response_model=DataSourceResponse,
)
def disable_source(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    source.status = "disabled"
    source.is_authorised = False
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="disable_data_source",
        result="success",
        metadata={"source_id": str(source_id), "source_key": source.source_key},
    )
    db.commit()
    db.refresh(source)
    return _source_payload(source)


@router.get(
    "/sources/{source_id}/health",
    response_model=ConnectorHealthResponse,
)
def check_source_health(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    details = {}
    reachable = True
    storage_available = True
    messages = []

    if source.base_url:
        try:
            response = requests.get(source.base_url, timeout=8)
            details["base_url_status_code"] = response.status_code
            reachable = response.status_code < 500
            if not reachable:
                messages.append(f"Base URL returned HTTP {response.status_code}.")
        except requests.RequestException as exc:
            reachable = False
            details["base_url_error"] = str(exc)
            messages.append("Base URL is not reachable.")

    if source.storage_path:
        path = Path(source.storage_path)
        storage_available = path.exists() and path.is_dir()
        details["storage_path"] = str(path)
        details["storage_exists"] = path.exists()
        if not storage_available:
            messages.append("Storage path is not available.")

    if source.status not in {"active"} or not source.is_authorised:
        messages.append("Source is not active and authorised.")

    health_status = "healthy" if reachable and storage_available and source.status == "active" and source.is_authorised else "degraded"
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "status": health_status,
        "reachable": reachable,
        "storage_available": storage_available,
        "message": " ".join(messages) if messages else "Connector health check passed.",
        "checked_at": datetime.now(timezone.utc),
        "details": details,
    }


@router.get(
    "/sources/{source_id}/schedule",
    response_model=ConnectorScheduleResponse,
)
def get_source_schedule(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    config = source.config or {}
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "refresh_policy": source.refresh_policy,
        "schedule": config.get("schedule", {}),
        "retry_policy": source.retry_policy or config.get("retry_policy", {}),
    }


@router.put(
    "/sources/{source_id}/schedule",
    response_model=ConnectorScheduleResponse,
)
def update_source_schedule(
    source_id: UUID,
    payload: ConnectorScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    config = dict(source.config or {})
    config["schedule"] = payload.schedule
    source.config = config
    source.refresh_policy = payload.refresh_policy or source.refresh_policy
    if payload.retry_policy:
        source.retry_policy = payload.retry_policy

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="update_source_schedule",
        result="success",
        metadata={
            "source_id": str(source_id),
            "schedule": payload.schedule,
            "retry_policy": payload.retry_policy,
        },
    )

    db.commit()
    db.refresh(source)
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "refresh_policy": source.refresh_policy,
        "schedule": source.config.get("schedule", {}) if source.config else {},
        "retry_policy": source.retry_policy or {},
    }


@router.get(
    "/sources/{source_id}/health/history",
)
def source_health_history(
    source_id: UUID,
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    jobs = (
        db.query(IngestionJob)
        .filter(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(limit)
        .all()
    )
    failures = (
        db.query(IngestionFailureEvent)
        .filter(IngestionFailureEvent.source_id == source_id)
        .order_by(IngestionFailureEvent.event_time.desc())
        .limit(limit)
        .all()
    )
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "status": source.status,
        "is_authorised": source.is_authorised,
        "last_success_at": source.last_success_at,
        "last_failure_at": source.last_failure_at,
        "consecutive_failures": source.consecutive_failures,
        "circuit_state": source.circuit_state,
        "recent_jobs": [
            {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "records_seen": job.records_seen,
                "records_loaded": job.records_loaded,
                "records_failed": job.records_failed,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
            }
            for job in jobs
        ],
        "recent_failures": [
            {
                "failure_id": failure.failure_id,
                "failure_stage": failure.failure_stage,
                "failure_category": failure.failure_category,
                "severity": failure.severity,
                "message": failure.message,
                "event_time": failure.event_time,
            }
            for failure in failures
        ],
    }


def _schedule_due_reason(source: DataSource, now: datetime) -> tuple[bool, str, str | None]:
    config = source.config or {}
    schedule = config.get("schedule", {}) if isinstance(config, dict) else {}
    if source.status != "active" or not source.is_authorised:
        return False, "source is not active/authorised", None
    if source.circuit_state == "open" and source.circuit_open_until and source.circuit_open_until > now:
        return False, "circuit breaker is open", source.circuit_open_until.isoformat()
    interval_hours = schedule.get("interval_hours") or schedule.get("every_hours")
    if not interval_hours:
        return False, "no interval schedule configured", None
    last_run = source.last_success_at or source.last_failure_at or source.created_at
    due_at = last_run + timedelta(hours=float(interval_hours))
    return now >= due_at, "schedule interval elapsed" if now >= due_at else "not due yet", due_at.isoformat()


@router.get(
    "/source-freshness",
    response_model=List[SourceFreshnessResponse],
)
def source_freshness_dashboard(
    tenant_id: UUID | None = None,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    enforce_requested_tenant(current_user, tenant_id)
    query = scope_query(db.query(DataSource), DataSource, current_user, include_shared=include_shared)
    sources = query.order_by(DataSource.source_category, DataSource.name).all()
    rows = []
    now = datetime.now(timezone.utc)
    for source in sources:
        latest_record_at = (
            db.query(func.max(RawIngestionRecord.created_at))
            .filter(RawIngestionRecord.source_id == source.source_id)
            .scalar()
        )
        latest_archive_at = (
            db.query(func.max(RawIngestionRecord.created_at))
            .filter(RawIngestionRecord.source_id == source.source_id, RawIngestionRecord.storage_uri.isnot(None))
            .scalar()
        )
        totals = (
            db.query(
                func.coalesce(func.sum(IngestionJob.records_seen), 0),
                func.coalesce(func.sum(IngestionJob.records_loaded), 0),
                func.coalesce(func.sum(IngestionJob.records_failed), 0),
            )
            .filter(IngestionJob.source_id == source.source_id)
            .first()
        )
        freshness_anchor = source.last_success_at or latest_record_at
        if not freshness_anchor:
            freshness_status = "never_loaded"
        elif source.last_failure_at and (not source.last_success_at or source.last_failure_at > source.last_success_at):
            freshness_status = "failing"
        elif (now - freshness_anchor).days > 30:
            freshness_status = "stale"
        else:
            freshness_status = "fresh"
        rows.append(
            {
                "source_id": source.source_id,
                "source_key": source.source_key,
                "tenant_id": source.tenant_id,
                "name": source.name,
                "source_category": source.source_category,
                "source_type": source.source_type,
                "status": source.status,
                "last_success_at": source.last_success_at,
                "last_failure_at": source.last_failure_at,
                "latest_record_at": latest_record_at,
                "latest_archive_at": latest_archive_at,
                "freshness_status": freshness_status,
                "records_seen": int(totals[0] or 0),
                "records_loaded": int(totals[1] or 0),
                "records_failed": int(totals[2] or 0),
            }
        )
    return rows


@router.get(
    "/readiness",
)
def ingestion_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source_counts = dict(
        db.query(DataSource.source_type, func.count(DataSource.source_id))
        .group_by(DataSource.source_type)
        .all()
    )
    category_counts = dict(
        db.query(DataSource.source_category, func.count(DataSource.source_id))
        .group_by(DataSource.source_category)
        .all()
    )
    record_counts = dict(
        db.query(RawIngestionRecord.record_type, func.count(RawIngestionRecord.record_id))
        .group_by(RawIngestionRecord.record_type)
        .all()
    )
    latest_jobs = (
        db.query(IngestionJob)
        .order_by(IngestionJob.created_at.desc())
        .limit(10)
        .all()
    )
    implemented = [
        "tenant_institution_source_model",
        "connector_registry_and_source_classification",
        "statsSA_qlfs_discovery_download_table_extraction",
        "che_vitalstats_discovery_download_table_extraction",
        "curriculum_upload_api_and_cput_prospectus_import",
        "job_dataset_upload_and_job_board_payload_simulation",
        "raw_archive_checksums_lineage_and_file_metadata",
        "data_quality_contracts_drift_checks_and_contract_cloning",
        "normaliser_registry_cleaned_records_and_review_queue",
        "source_health_retry_backoff_freshness_and_due_schedule_monitoring",
        "secure_credential_storage_api_surface",
    ]
    deferred = [
        "live_linkedin_indeed_pnet_careerjunction_api_clients_waiting_for_provider_access",
        "full_background_scheduler_worker",
        "vault_or_external_secret_manager",
        "full_table_by_table_statsSA_and_che_mapping_catalogue",
        "rich_spreadsheet_style_manual_row_editor",
        "strict_rbac_tenant_isolation_policy_enforcement",
    ]
    return {
        "phase": "ingestion_foundation_closed_for_processing",
        "summary": (
            "The ingestion layer is ready to support the processing phase with current "
            "available sources: curriculum evidence, labour-market trends, current-job "
            "datasets, CHE context data, and simulated job-board API payloads."
        ),
        "source_counts": source_counts,
        "category_counts": category_counts,
        "record_counts": record_counts,
        "implemented": implemented,
        "deferred": deferred,
        "latest_jobs": [
            {
                "job_id": job.job_id,
                "source_id": job.source_id,
                "job_type": job.job_type,
                "status": job.status,
                "records_seen": job.records_seen,
                "records_loaded": job.records_loaded,
                "records_failed": job.records_failed,
                "created_at": job.created_at,
            }
            for job in latest_jobs
        ],
    }


@router.get(
    "/schedules/due",
    response_model=List[DueScheduleResponse],
)
def list_due_schedules(
    tenant_id: UUID | None = None,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    enforce_requested_tenant(current_user, tenant_id)
    query = scope_query(db.query(DataSource), DataSource, current_user, include_shared=include_shared)
    now = datetime.now(timezone.utc)
    response = []
    for source in query.order_by(DataSource.name).all():
        due, reason, next_run_hint = _schedule_due_reason(source, now)
        response.append(
            {
                "source_id": source.source_id,
                "source_key": source.source_key,
                "name": source.name,
                "due": due,
                "reason": reason,
                "next_run_hint": next_run_hint,
                "schedule": (source.config or {}).get("schedule", {}),
            }
        )
    return response


@router.post(
    "/schedules/run-due",
)
def enqueue_due_schedules(
    tenant_id: UUID | None = None,
    include_shared: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    enforce_requested_tenant(current_user, tenant_id)
    query = scope_query(db.query(DataSource), DataSource, current_user, include_shared=include_shared)
    now = datetime.now(timezone.utc)
    jobs = []
    for source in query.all():
        due, reason, _ = _schedule_due_reason(source, now)
        if not due:
            continue
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type="scheduled_ingestion_due",
            triggered_by=current_user.identity_id,
            parameters={"reason": reason, "connector_type": source.connector_type},
        )
        jobs.append({"job_id": job.job_id, "source_id": source.source_id, "source_key": source.source_key})
    db.commit()
    return {"queued": len(jobs), "jobs": jobs}


@router.get(
    "/job-board/contracts",
)
def job_board_payload_contracts(
    current_user: User = Depends(get_current_user),
):
    return job_board_api_connector.sample_contracts()


@router.post(
    "/job-board/simulate",
    response_model=JobBoardSimulationResponse,
    status_code=status.HTTP_201_CREATED,
)
def simulate_job_board_ingestion(
    payload: JobBoardSimulationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    records = payload.payloads
    if not records and payload.use_sample_when_empty:
        records = [job_board_api_connector.sample_payload(payload.provider)]
    if not records:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide payloads or enable use_sample_when_empty",
        )
    result = job_board_api_connector.ingest_payloads(
        db=db,
        provider=payload.provider,
        payloads=records,
        actor_id=current_user.identity_id,
        tenant_id=str(payload.tenant_id) if payload.tenant_id else None,
        source_label=payload.source_label,
    )
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="job_board_payload",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.job_board",
        action="simulate_job_board_ingestion",
        result="success",
        metadata=result,
    )
    db.commit()
    return result


@router.post(
    "/sources/{source_id}/auth/test",
)
def test_source_credentials(
    source_id: UUID,
    payload: CredentialTestRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    supplied_auth = payload.auth_config if payload else None
    auth_config = supplied_auth or credential_service.decrypt_config(source.auth_config or {})
    details: Dict[str, Any] = {
        "requires_auth": bool(auth_config or source.auth_config),
        "auth_type": auth_config.get("type") or auth_config.get("auth_type") or "none",
    }
    status_text = "not_required"
    message = "No credential configuration is required for this source."

    if source.base_url:
        try:
            headers = {}
            if auth_config.get("api_key"):
                header_name = auth_config.get("api_key_header", "Authorization")
                prefix = auth_config.get("api_key_prefix", "Bearer")
                headers[header_name] = f"{prefix} {auth_config['api_key']}".strip()
            response = requests.get(source.base_url, headers=headers, timeout=8)
            details["base_url_status_code"] = response.status_code
            status_text = "passed" if response.status_code < 500 else "warning"
            message = "Source endpoint responded to the credential test."
        except requests.RequestException as exc:
            details["error"] = str(exc)
            status_text = "failed"
            message = "Source endpoint could not be reached with the supplied credential configuration."

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="test_source_credentials",
        result=status_text,
        metadata={"source_id": str(source_id), "auth_type": details["auth_type"]},
    )
    db.commit()
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "status": status_text,
        "message": message,
        "checked_at": datetime.now(timezone.utc),
        "details": details,
    }


@router.get(
    "/sources/{source_id}/credentials",
    response_model=CredentialStatusResponse,
)
def get_source_credentials_status(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    auth_config = source.auth_config or {}
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "has_credentials": bool(auth_config),
        "auth_config": credential_service.mask_config(auth_config),
        "fingerprint": credential_service.fingerprint(auth_config) if auth_config else None,
    }


@router.put(
    "/sources/{source_id}/credentials",
    response_model=CredentialStatusResponse,
)
def save_source_credentials(
    source_id: UUID,
    payload: CredentialSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )
    source.auth_config = credential_service.encrypt_config(payload.auth_config or {})
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_source",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="save_source_credentials",
        result="success",
        metadata={"source_id": str(source_id), "fingerprint": credential_service.fingerprint(source.auth_config)},
    )
    db.commit()
    db.refresh(source)
    return {
        "source_id": source.source_id,
        "source_key": source.source_key,
        "has_credentials": bool(source.auth_config),
        "auth_config": credential_service.mask_config(source.auth_config or {}),
        "fingerprint": credential_service.fingerprint(source.auth_config or {}),
    }


@router.get(
    "/contracts",
    response_model=List[IngestionContractResponse],
)
def list_contracts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return data_quality_service.list_contracts(db)


@router.put(
    "/contracts/{contract_id}",
    response_model=IngestionContractResponse,
)
def update_contract(
    contract_id: UUID,
    payload: IngestionContractUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    contract = (
        db.query(IngestionContract)
        .filter(IngestionContract.contract_id == contract_id)
        .first()
    )
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion contract not found",
        )

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(contract, field, value)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_contract",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="update_ingestion_contract",
        result="success",
        metadata={"contract_id": str(contract_id), "updated_fields": sorted(updates.keys())},
    )
    db.commit()
    db.refresh(contract)
    return contract


@router.post(
    "/contracts/{contract_id}/clone",
    response_model=IngestionContractResponse,
    status_code=status.HTTP_201_CREATED,
)
def clone_contract(
    contract_id: UUID,
    payload: ContractCloneRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    source_contract = (
        db.query(IngestionContract)
        .filter(IngestionContract.contract_id == contract_id)
        .first()
    )
    if not source_contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion contract not found",
        )
    existing = (
        db.query(IngestionContract)
        .filter(
            IngestionContract.source_id == source_contract.source_id,
            IngestionContract.contract_key == source_contract.contract_key,
            IngestionContract.version == payload.version,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A contract with this key and version already exists for the source",
        )
    clone = IngestionContract(
        source_id=source_contract.source_id,
        contract_key=source_contract.contract_key,
        name=payload.name or f"{source_contract.name} v{payload.version}",
        version=payload.version,
        record_type=source_contract.record_type,
        description=source_contract.description,
        schema_definition=source_contract.schema_definition or {},
        cleaning_profile=source_contract.cleaning_profile or {},
        quality_thresholds=source_contract.quality_thresholds or {},
        status=payload.status,
    )
    db.add(clone)
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_contract",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="clone_ingestion_contract",
        result="success",
        metadata={"source_contract_id": str(contract_id), "new_version": payload.version},
    )
    db.commit()
    db.refresh(clone)
    return clone


def _schema_expected_fields(schema_definition: Dict[str, Any]) -> set[str]:
    if not schema_definition:
        return set()
    fields = schema_definition.get("required_fields") or schema_definition.get("fields") or []
    if isinstance(fields, dict):
        return set(fields.keys())
    return {str(item) for item in fields if item}


def _payload_fields(record: RawIngestionRecord) -> set[str]:
    fields = set()
    for payload in (record.raw_payload or {}, record.normalised_payload or {}):
        if isinstance(payload, dict):
            fields.update(str(key) for key in payload.keys())
            row = payload.get("row")
            if isinstance(row, dict):
                fields.update(str(key) for key in row.keys())
            rows = payload.get("rows")
            if isinstance(rows, list):
                for item in rows[:5]:
                    if isinstance(item, dict):
                        fields.update(str(key) for key in item.keys())
    return fields


@router.get(
    "/contracts/{contract_id}/drift",
    response_model=ContractDriftReportResponse,
)
def contract_drift_report(
    contract_id: UUID,
    limit: int = Query(default=250, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contract = (
        db.query(IngestionContract)
        .filter(IngestionContract.contract_id == contract_id)
        .first()
    )
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion contract not found",
        )

    expected = _schema_expected_fields(contract.schema_definition or {})
    records = (
        db.query(RawIngestionRecord)
        .filter(
            RawIngestionRecord.source_id == contract.source_id,
            RawIngestionRecord.record_type == contract.record_type,
        )
        .order_by(RawIngestionRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    missing_counter: Counter[str] = Counter()
    unexpected_counter: Counter[str] = Counter()
    for record in records:
        observed = _payload_fields(record)
        for field in expected - observed:
            missing_counter[field] += 1
        if expected:
            for field in observed - expected:
                unexpected_counter[field] += 1

    drift_events = sum(missing_counter.values()) + sum(unexpected_counter.values())
    denominator = max(1, len(records) * max(1, len(expected)))
    drift_score = min(1.0, drift_events / denominator)
    status_text = "changed" if drift_score >= 0.2 else "watch" if drift_score > 0 else "stable"
    return {
        "contract_id": contract.contract_id,
        "contract_key": contract.contract_key,
        "record_type": contract.record_type,
        "records_checked": len(records),
        "missing_fields": [
            {"field": field, "count": count}
            for field, count in missing_counter.most_common(25)
        ],
        "unexpected_fields": [
            {"field": field, "count": count}
            for field, count in unexpected_counter.most_common(25)
        ],
        "status": status_text,
        "drift_score": round(drift_score, 4),
    }


@router.get(
    "/jobs",
    response_model=List[IngestionJobResponse],
)
def list_jobs(
    status_filter: str | None = None,
    job_type: str | None = None,
    unprocessed_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(IngestionJob)
    if status_filter:
        query = query.filter(IngestionJob.status == status_filter)
    if job_type:
        query = query.filter(IngestionJob.job_type == job_type)
    if unprocessed_only:
        query = query.filter(IngestionJob.processed == False)
    jobs = query.order_by(IngestionJob.created_at.desc()).limit(100).all()
    for job in jobs:
        # The relationship is joined, but these presentation fields were not
        # previously part of the response schema.  Expose them explicitly so
        # portal provenance does not depend on guessing from job_type.
        job.source_key = job.source.source_key if job.source else None
        job.source_name = job.source.name if job.source else None
    return jobs


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobDetailResponse,
)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    records = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.job_id == job.job_id)
        .order_by(RawIngestionRecord.created_at.asc())
        .limit(200)
        .all()
    )

    lineage = (
        db.query(DataLineageEvent)
        .filter(DataLineageEvent.job_id == job.job_id)
        .order_by(DataLineageEvent.event_time.asc())
        .limit(200)
        .all()
    )

    return {
        "job": job,
        "records": records,
        "lineage": lineage,
    }


@router.get(
    "/jobs/{job_id}/failures",
    response_model=List[IngestionFailureEventResponse],
)
def list_job_failures(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )
    return (
        db.query(IngestionFailureEvent)
        .filter(IngestionFailureEvent.job_id == job_id)
        .order_by(IngestionFailureEvent.event_time.desc())
        .all()
    )


@router.post(
    "/jobs/{job_id}/retry",
    response_model=IngestionRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_ingestion_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    job = ingestion_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )
    if job.status == "retry_scheduled" and job.next_retry_at and job.next_retry_at > datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Retry is already scheduled for this job",
        )

    try:
        retry_job = ingestion_job_service.create_retry_job(
            db=db,
            failed_job=job,
            triggered_by=current_user.identity_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_job",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="retry_ingestion_job",
        result="accepted",
        metadata={
            "original_job_id": str(job.job_id),
            "retry_job_id": str(retry_job.job_id),
            "attempt_number": retry_job.attempt_number,
        },
    )
    db.commit()
    db.refresh(job)
    db.refresh(retry_job)
    return {
        "message": "Retry job queued",
        "original_job": job,
        "retry_job": retry_job,
    }


@router.get(
    "/failures",
    response_model=List[IngestionFailureEventResponse],
)
def list_ingestion_failures(
    source_id: UUID | None = None,
    failure_category: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(IngestionFailureEvent)
    if source_id:
        query = query.filter(IngestionFailureEvent.source_id == source_id)
    if failure_category:
        query = query.filter(IngestionFailureEvent.failure_category == failure_category)
    return query.order_by(IngestionFailureEvent.event_time.desc()).limit(200).all()


@router.post(
    "/jobs/{job_id}/quality/run",
    response_model=DataQualityRunResponse,
)
def run_job_quality_checks(
    job_id: UUID,
    payload: DataQualityRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    summary = data_quality_service.run_job_quality(
        db=db,
        job=job,
        actor_id=current_user.identity_id,
        limit=payload.limit,
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_quality",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.quality",
        action="run_quality_checks",
        result="success",
        metadata=summary,
    )

    db.commit()
    return summary


@router.get(
    "/jobs/{job_id}/quality/summary",
    response_model=DataQualitySummaryResponse,
)
def get_job_quality_summary(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return data_quality_service.job_quality_summary(db, job_id)


@router.get(
    "/jobs/{job_id}/quality/checks",
    response_model=List[DataQualityCheckResponse],
)
def list_job_quality_checks(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return (
        db.query(DataQualityCheck)
        .filter(DataQualityCheck.job_id == job.job_id)
        .order_by(DataQualityCheck.created_at.desc())
        .limit(1000)
        .all()
    )


@router.get(
    "/jobs/{job_id}/quality/failure-report",
    response_model=QualityFailureReportResponse,
)
def get_job_quality_failure_report(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    failed_or_warned = (
        db.query(DataQualityCheck)
        .filter(
            DataQualityCheck.job_id == job.job_id,
            DataQualityCheck.status.in_(["failed", "warning"]),
        )
        .order_by(DataQualityCheck.created_at.desc())
        .limit(1000)
        .all()
    )
    failures = [item for item in failed_or_warned if item.status == "failed"]
    warnings = [item for item in failed_or_warned if item.status == "warning"]

    def grouped(checks: List[DataQualityCheck]) -> List[dict]:
        counts = Counter(
            (
                item.check_metadata.get("rule_key")
                if item.check_metadata
                else item.rule_id
            )
            or item.message
            for item in checks
        )
        return [
            {"rule_or_message": str(key), "count": value}
            for key, value in counts.most_common()
        ]

    return {
        "job_id": job.job_id,
        "total_failures": len(failures),
        "total_warnings": len(warnings),
        "failure_groups": grouped(failures),
        "warning_groups": grouped(warnings),
        "sample_failures": failures[:25],
    }


@router.post("/jobs/{job_id}/import")
def import_job_data(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
) -> Dict[str, Any]:
    job = ingestion_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    if job.status != "completed":
        raise HTTPException(status_code=422, detail=f"Job status is '{job.status}'; must be 'completed' to import")
    if job.imported:
        return {
            "job_id": str(job_id),
            "already_imported": True,
            "files_processed": 0,
            "total_rows_imported": 0,
            "total_errors": 0,
            "files": [],
            "message": "This job has already been imported.",
        }

    raw_records = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.job_id == job.job_id)
        .order_by(RawIngestionRecord.record_id)
        .all()
    )
    if not raw_records:
        raise HTTPException(status_code=422, detail="Job has no raw records to import")

    from app.services.generic_import_service import import_job_records
    result = import_job_records(db, job_id, raw_records)

    imported_rows = int(result.get("total_rows_imported") or 0)
    skipped_files = [item for item in result.get("files", []) if item.get("skipped")]
    if imported_rows <= 0 and skipped_files:
        ingestion_job_service.mark_failed(
            db=db,
            job=job,
            error="No supported records were imported. " + "; ".join(
                f"{item.get('filename', 'file')}: {item.get('reason', 'unsupported')}" for item in skipped_files[:5]
            ),
            failure_stage="generic_import",
            failure_category="unsupported_format",
            diagnostic_payload={"import_result": result},
        )
    else:
        job.imported = True

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="generic_csv_import",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="import_job_data",
        result="completed",
        metadata={
            "job_id": str(job_id),
            "files_processed": result["files_processed"],
            "total_rows_imported": result["total_rows_imported"],
            "total_errors": result["total_errors"],
        },
    )
    db.commit()
    return result


def _run_async_import(
    job_id: UUID,
    auto_enrich: bool,
):
    """Background thread: stream-import job postings, then optionally enrich."""
    from app.db.session import SessionLocal
    from app.services.generic_import_service import import_job_records
    from app.models.ingestion_job import IngestionJob
    from app.models.raw_ingestion_record import RawIngestionRecord

    db = SessionLocal()
    try:
        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        if not job:
            log.error("Async import: job %s not found", job_id)
            return

        raw_records = (
            db.query(RawIngestionRecord)
            .filter(RawIngestionRecord.job_id == job.job_id)
            .order_by(RawIngestionRecord.record_id)
            .all()
        )
        if not raw_records:
            log.error("Async import: job %s has no raw records", job_id)
            ingestion_job_service.mark_failed(
                db=db, job=job, error="No raw records found",
                failure_stage="async_import", failure_category="data_error",
            )
            db.commit()
            return

        def _on_progress(processed, total, partial):
            try:
                job.progress_current = processed
                job.last_heartbeat_at = datetime.now(timezone.utc)
                if partial:
                    job.failure_details = {
                        **(job.failure_details or {}),
                        "import_progress": partial,
                    }
                db.add(job)
                db.commit()
            except Exception:
                db.rollback()

        result = import_job_records(db, job_id, raw_records, on_progress=_on_progress)

        job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
        imported_rows = int(result.get("total_rows_imported") or 0)
        skipped_files = [item for item in result.get("files", []) if item.get("skipped")]
        job.progress_current = job.progress_total or len(raw_records)
        job.failure_details = {
            **(job.failure_details or {}),
            "import_progress": {
                "files_processed": result["files_processed"],
                "total_rows_imported": result["total_rows_imported"],
                "total_errors": result["total_errors"],
            },
            "import_result": {
                "files_processed": result["files_processed"],
                "total_rows_imported": result["total_rows_imported"],
                "total_errors": result["total_errors"],
            },
        }
        if imported_rows <= 0 and skipped_files:
            ingestion_job_service.mark_failed(
                db=db,
                job=job,
                error="No supported records were imported. " + "; ".join(
                    f"{item.get('filename', 'file')}: {item.get('reason', 'unsupported')}" for item in skipped_files[:5]
                ),
                failure_stage="generic_import",
                failure_category="unsupported_format",
                diagnostic_payload={"import_result": result},
            )
        else:
            job.imported = True
            ingestion_job_service.mark_completed(db=db, job=job)
        db.add(job)
        db.commit()

        log.info(
            "Async import complete for job %s: %d rows imported, %d errors",
            job_id, result["total_rows_imported"], result["total_errors"],
        )

        if auto_enrich and result["total_rows_imported"] > 0:
            try:
                from app.services.vector_enrichment_service import vector_enrichment_service
                log.info("Auto-enriching job postings from job %s", job_id)
                enrich_result = vector_enrichment_service.enrich_job_postings_batch(
                    db=db, limit=5000, top_skill_k=10, top_occ_k=3,
                    min_skill_score=0.35, min_occ_score=0.35,
                )
                log.info("Auto-enrichment complete: %s", enrich_result.get("enriched", 0))
            except Exception as exc:
                log.warning("Auto-enrichment failed: %s", exc)

    except Exception as exc:
        log.error("Async import failed for job %s: %s", job_id, exc)
        try:
            job = db.query(IngestionJob).filter(IngestionJob.job_id == job_id).first()
            if job:
                ingestion_job_service.mark_failed(
                    db=db, job=job, error=str(exc),
                    failure_stage="async_import", failure_category="system_error",
                )
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/jobs/{job_id}/import-async", status_code=status.HTTP_202_ACCEPTED)
def import_job_data_async(
    job_id: UUID,
    auto_enrich: bool = Query(default=True, description="Auto-enrich job postings with ESCO matches after import"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
) -> Dict[str, Any]:
    """Start an async background import for a completed ingestion job.

    Streams large CSV files in chunks (5000 rows per commit).
    Optionally auto-enriches imported job postings with ESCO matches.
    """
    job = ingestion_job_service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    if job.status != "completed":
        raise HTTPException(status_code=422, detail=f"Job status is '{job.status}'; must be 'completed' to import")
    if job.imported:
        return {
            "job_id": str(job_id),
            "already_imported": True,
            "message": "This job has already been imported.",
        }

    raw_count = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.job_id == job.job_id)
        .count()
    )
    ingestion_job_service.mark_running(db=db, job=job, total=raw_count)
    job.progress_current = 0
    job.failure_details = {
        **(job.failure_details or {}),
        "import_progress": {
            "status": "accepted",
            "files_processed": 0,
            "total_files": raw_count,
        },
    }
    db.add(job)
    db.commit()

    operational_job, created = operational_job_service.enqueue(
        db=db,
        job_type="ingestion.generic_import",
        requested_by=current_user.identity_id,
        parameters={
            "ingestion_job_id": str(job_id),
            "auto_enrich": auto_enrich,
        },
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="generic_csv_import",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="import_job_data_async",
        result="accepted",
        metadata={
            "job_id": str(job_id),
            "operational_job_id": str(operational_job.job_id),
            "auto_enrich": auto_enrich,
            "created": created,
        },
    )
    db.commit()

    return {
        "job_id": str(job_id),
        "message": "Import accepted by the durable worker.",
        "auto_enrich": auto_enrich,
        "operational_job": operational_job_service.to_dict(operational_job),
    }


@router.get(
    "/jobs/{job_id}/cleaned-records",
    response_model=List[CleanedIngestionRecordResponse],
)
def list_job_cleaned_records(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return (
        db.query(CleanedIngestionRecord)
        .filter(CleanedIngestionRecord.job_id == job.job_id)
        .order_by(CleanedIngestionRecord.created_at.desc())
        .limit(1000)
        .all()
    )


@router.get(
    "/sources/{source_id}/files",
    response_model=List[SourceFileArchiveResponse],
)
def list_source_files(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    source = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data source not found",
        )

    records = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.source_id == source_id)
        .order_by(RawIngestionRecord.created_at.desc())
        .limit(5000)
        .all()
    )
    buckets: Dict[str, Dict[str, Any]] = {}
    for record in records:
        raw_payload = record.raw_payload or {}
        source_file = (
            raw_payload.get("source_file")
            or raw_payload.get("filename")
            or raw_payload.get("file")
            or (Path(record.storage_uri).name if record.storage_uri else None)
        )
        key = record.storage_uri or source_file or record.content_hash or str(record.record_id)
        bucket = buckets.setdefault(
            str(key),
            {
                "source_id": source.source_id,
                "source_key": source.source_key,
                "storage_uri": record.storage_uri,
                "source_file": source_file,
                "content_hash": record.content_hash,
                "first_seen_at": record.created_at,
                "latest_seen_at": record.created_at,
                "record_count": 0,
                "duplicate_count": 0,
                "record_types": set(),
            },
        )
        bucket["record_count"] += 1
        bucket["record_types"].add(record.record_type)
        bucket["first_seen_at"] = min(bucket["first_seen_at"], record.created_at)
        bucket["latest_seen_at"] = max(bucket["latest_seen_at"], record.created_at)

    seen_hashes: Counter[str] = Counter(
        record.content_hash for record in records if record.content_hash
    )
    now = datetime.now(timezone.utc)
    response = []
    for bucket in buckets.values():
        if bucket["content_hash"]:
            bucket["duplicate_count"] = max(0, seen_hashes[bucket["content_hash"]] - 1)
        age_days = (now - bucket["latest_seen_at"]).days if bucket["latest_seen_at"] else 9999
        bucket["freshness_status"] = "fresh" if age_days <= 30 else "stale" if age_days <= 180 else "old"
        bucket["record_types"] = sorted(bucket["record_types"])
        response.append(bucket)
    return sorted(response, key=lambda item: item["latest_seen_at"], reverse=True)[:500]


@router.get(
    "/files/download",
)
def download_source_file(
    storage_uri: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.storage_uri == storage_uri)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File record not found",
        )
    path = Path(storage_uri)
    if not path.exists() or not path.is_file():
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "archive_status": "metadata_only",
                "message": "Archived file is not available on disk; returning captured raw payload instead.",
                "storage_uri": storage_uri,
                "record_id": str(record.record_id),
                "source_id": str(record.source_id) if record.source_id else None,
                "record_type": record.record_type,
                "content_hash": record.content_hash,
                "raw_payload": record.raw_payload,
                "normalised_payload": record.normalised_payload,
            },
        )
    return FileResponse(path, filename=path.name)



@router.post("/generic-intake", status_code=status.HTTP_202_ACCEPTED)
def generic_source_intake(
    intake_mode: str = Form(...),
    source_category: str = Form(...),
    source_type: str = Form(default="other"),
    source_name: str = Form(default="Other"),
    other_source_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    endpoint_url: str | None = Form(default=None),
    api_method: str = Form(default="GET"),
    api_payload: str | None = Form(default=None),
    requires_auth: bool = Form(default=False),
    username: str | None = Form(default=None),
    password: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
) -> Dict[str, Any]:
    mode = (intake_mode or "").strip().lower()
    if mode not in {"file", "website", "api"}:
        raise HTTPException(status_code=422, detail="intake_mode must be file, website, or api")

    category = (source_category or "other").strip().lower()
    selected_source = (source_name or "Other").strip()
    final_source_name = (other_source_name or selected_source).strip() if selected_source.lower() == "other" else selected_source
    if not final_source_name:
        final_source_name = "Generic Source"

    if mode == "file" and not file:
        raise HTTPException(status_code=422, detail="A file is required for file intake")
    if mode in {"website", "api"} and not endpoint_url:
        raise HTTPException(status_code=422, detail="endpoint_url is required for website or api intake")

    source_type_value = _slug(source_type if source_type != "other" else final_source_name, "other")[:50]
    source_key = f"generic_{category}_{source_type_value}_{_slug(final_source_name)}"[:100]
    connector_type = "generic_source_intake"

    config = {
        "description": description,
        "intake_mode": mode,
        "declared_source_name": selected_source,
        "other_source_name": other_source_name,
        "endpoint_url": endpoint_url,
        "api_method": api_method.upper(),
        "supports_generic_pipeline": True,
    }
    auth_config = {
        "requires_auth": bool(requires_auth),
        "username": username if requires_auth and username else None,
        "password_provided": bool(requires_auth and password),
        "storage_note": "Password is used for immediate request only and is not stored by generic intake.",
    }

    source = ingestion_job_service.get_or_create_source(
        db=db,
        source_key=source_key,
        defaults={
            "name": final_source_name,
            "source_type": source_type_value,
            "source_category": category,
            "connector_type": connector_type,
            "source_scope": "shared",
            "ingestion_mode": "manual",
            "source_format": "unknown",
            "normaliser_key": None,
            "base_url": endpoint_url,
            "storage_path": str(Path("data") / "generic_intake" / source_key),
            "refresh_policy": "manual",
            "retry_policy": {},
            "owner": current_user.identity_id,
            "status": "active",
            "is_authorised": True,
            "config": config,
            "auth_config": auth_config,
        },
    )
    source.name = final_source_name
    source.source_category = category
    source.source_type = source_type_value
    source.connector_type = connector_type
    source.ingestion_mode = "manual"
    source.base_url = endpoint_url
    source.config = {**(source.config or {}), **config}
    source.auth_config = auth_config
    source.is_authorised = True
    db.add(source)
    db.flush()

    job = ingestion_job_service.create_job(
        db=db,
        source=source,
        job_type="generic_source_intake",
        triggered_by=current_user.identity_id,
        parameters={
            "intake_mode": mode,
            "source_category": category,
            "source_type": source_type_value,
            "source_name": final_source_name,
            "endpoint_url": endpoint_url,
            "description": description,
        },
    )
    ingestion_job_service.mark_running(db, job, total=1)

    try:
        content_type = None
        filename = None
        status_code = None
        data: bytes
        source_record_id = None

        if mode == "file":
            assert file is not None
            filename = file.filename or "uploaded_payload"
            content_type = file.content_type
            data = file.file.read()
            if not data:
                raise ValueError("Uploaded file is empty")
            source_record_id = filename
        else:
            method = api_method.upper() if mode == "api" else "GET"
            if method not in {"GET", "POST"}:
                raise ValueError("api_method must be GET or POST")
            request_kwargs: Dict[str, Any] = {"timeout": 30}
            if requires_auth and username and password:
                request_kwargs["auth"] = (username, password)
            if method == "POST":
                request_kwargs["headers"] = {"Content-Type": "application/json"}
                request_kwargs["data"] = api_payload or "{}"
                response = requests.post(endpoint_url, **request_kwargs)
            else:
                response = requests.get(endpoint_url, **request_kwargs)
            status_code = response.status_code
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            filename = Path(endpoint_url or "remote_payload").name or f"{mode}_payload"
            data = response.content
            source_record_id = endpoint_url

        source_format = _guess_source_format(filename, content_type, fallback="html" if mode == "website" else "json" if mode == "api" else "unknown")
        storage_uri, digest = _store_generic_payload(source_key=source.source_key, filename=filename or "payload", data=data)
        source.source_format = source_format
        source.storage_path = str(Path(storage_uri).parent)
        db.add(source)
        db.flush()

        preview = _safe_text_preview(data)
        parsed_payload: Dict[str, Any] | List[Any] | None = None
        parse_status = "not_parsed"
        if source_format == "json" and preview:
            try:
                parsed_payload = json.loads(preview)
                parse_status = "parsed_json"
            except Exception:
                parse_status = "json_preview_only"

        raw_payload = {
            "intake_mode": mode,
            "source_category": category,
            "source_type": source_type_value,
            "source_name": final_source_name,
            "description": description,
            "filename": filename,
            "content_type": content_type,
            "source_format": source_format,
            "size_bytes": len(data),
            "endpoint_url": endpoint_url,
            "http_status_code": status_code,
            "text_preview": preview,
            "parse_status": parse_status,
            "parsed_payload": parsed_payload,
        }
        normalised_payload = {
            "source_name": final_source_name,
            "source_category": category,
            "source_type": source_type_value,
            "source_format": source_format,
            "description": description,
            "storage_uri": storage_uri,
            "content_hash": digest,
            "needs_normalisation": True,
            "generic_pipeline_stage": "raw_archived",
        }
        record = ingestion_job_service.add_raw_record(
            db=db,
            job=job,
            record_type=_generic_record_type(category, source_format),
            raw_payload=raw_payload,
            source_record_id=source_record_id,
            storage_uri=storage_uri,
            content_hash=digest,
            validation_status="pending",
            normalised_payload=normalised_payload,
        )
        ingestion_job_service.update_progress(db, job, current=1, total=1, seen_delta=1, loaded_delta=1)
        ingestion_job_service.mark_completed(db, job)

        log_audit_event(
            db=db,
            event_layer="application",
            event_type="generic_source_intake",
            actor_type=current_user.identity_type,
            actor_id=current_user.identity_id,
            token_id=None,
            source_component="ingestion.api",
            action="generic_source_intake",
            result="accepted",
            metadata={
                "job_id": str(job.job_id),
                "source_id": str(source.source_id),
                "record_id": str(record.record_id),
                "source_category": category,
                "source_format": source_format,
                "intake_mode": mode,
            },
        )
        db.commit()
        db.refresh(job)
        db.refresh(source)
        return {
            "message": "Generic source intake completed and queued for normalisation/review.",
            "job": IngestionJobResponse.model_validate(job).model_dump(mode="json"),
            "source": _source_payload(source),
            "record_id": str(record.record_id),
            "storage_uri": storage_uri,
        }
    except Exception as exc:
        ingestion_job_service.update_progress(db, job, current=1, total=1, seen_delta=1, failed_delta=1)
        ingestion_job_service.mark_failed(
            db=db,
            job=job,
            error=str(exc),
            failure_stage="generic_intake",
            failure_category=ingestion_job_service.classify_exception(exc),
            retryable=False,
            diagnostic_payload={"intake_mode": mode, "endpoint_url": endpoint_url, "source_name": final_source_name},
        )
        log_audit_event(
            db=db,
            event_layer="application",
            event_type="generic_source_intake",
            actor_type=current_user.identity_type,
            actor_id=current_user.identity_id,
            token_id=None,
            source_component="ingestion.api",
            action="generic_source_intake",
            result="failed",
            metadata={"job_id": str(job.job_id), "error": str(exc)},
        )
        db.commit()
        db.refresh(job)
        return JSONResponse(
            status_code=202,
            content={
                "message": "Generic source intake failed; failure is visible in Ingestion Jobs.",
                "job": IngestionJobResponse.model_validate(job).model_dump(mode="json"),
                "error": str(exc),
            },
        )


@router.post("/generic-intake-batch", status_code=status.HTTP_202_ACCEPTED)
def generic_source_intake_batch(
    intake_mode: str = Form(...),
    source_category: str = Form(...),
    source_type: str = Form(default="other"),
    source_name: str = Form(default="Other"),
    other_source_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
) -> Dict[str, Any]:
    mode = (intake_mode or "").strip().lower()
    if mode != "file":
        raise HTTPException(status_code=422, detail="Batch intake only supports file mode")
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    category = (source_category or "other").strip().lower()
    selected_source = (source_name or "Other").strip()
    final_source_name = (other_source_name or selected_source).strip() if selected_source.lower() == "other" else selected_source
    if not final_source_name:
        final_source_name = "Generic Source"

    source_type_value = _slug(source_type if source_type != "other" else final_source_name, "other")[:50]
    source_key = f"generic_{category}_{source_type_value}_{_slug(final_source_name)}"[:100]
    connector_type = "generic_source_intake"

    config = {
        "description": description,
        "intake_mode": mode,
        "declared_source_name": selected_source,
        "other_source_name": other_source_name,
        "supports_generic_pipeline": True,
        "batch_size": len(files),
    }
    auth_config = {"requires_auth": False}

    source = ingestion_job_service.get_or_create_source(
        db=db,
        source_key=source_key,
        defaults={
            "name": final_source_name,
            "source_type": source_type_value,
            "source_category": category,
            "connector_type": connector_type,
            "source_scope": "shared",
            "ingestion_mode": "manual",
            "source_format": "unknown",
            "normaliser_key": None,
            "storage_path": str(Path("data") / "generic_intake" / source_key),
            "refresh_policy": "manual",
            "retry_policy": {},
            "owner": current_user.identity_id,
            "status": "active",
            "is_authorised": True,
            "config": config,
            "auth_config": auth_config,
        },
    )
    source.name = final_source_name
    source.source_category = category
    source.source_type = source_type_value
    source.connector_type = connector_type
    source.ingestion_mode = "manual"
    source.config = {**(source.config or {}), **config}
    source.auth_config = auth_config
    source.is_authorised = True
    db.add(source)
    db.flush()

    job = ingestion_job_service.create_job(
        db=db,
        source=source,
        job_type="generic_source_intake",
        triggered_by=current_user.identity_id,
        parameters={
            "intake_mode": mode,
            "source_category": category,
            "source_type": source_type_value,
            "source_name": final_source_name,
            "description": description,
            "batch_size": len(files),
        },
    )
    ingestion_job_service.mark_running(db, job, total=len(files))

    loaded = 0
    failed = 0
    record_ids = []
    errors = []

    for idx, upload_file in enumerate(files):
        try:
            filename = upload_file.filename or f"upload_{idx}"
            content_type = upload_file.content_type
            data = upload_file.file.read()
            if not data:
                failed += 1
                errors.append(f"{filename}: empty file")
                continue

            source_format = _guess_source_format(filename, content_type, fallback="unknown")
            storage_uri, digest = _store_generic_payload(source_key=source.source_key, filename=filename, data=data)

            preview = _safe_text_preview(data)
            parsed_payload = None
            parse_status = "not_parsed"
            if source_format == "json" and preview:
                try:
                    parsed_payload = json.loads(preview)
                    parse_status = "parsed_json"
                except Exception:
                    parse_status = "json_preview_only"

            raw_payload = {
                "intake_mode": mode,
                "source_category": category,
                "source_type": source_type_value,
                "source_name": final_source_name,
                "description": description,
                "filename": filename,
                "content_type": content_type,
                "source_format": source_format,
                "size_bytes": len(data),
                "text_preview": preview,
                "parse_status": parse_status,
                "parsed_payload": parsed_payload,
                "batch_index": idx,
            }
            normalised_payload = {
                "source_name": final_source_name,
                "source_category": category,
                "source_type": source_type_value,
                "source_format": source_format,
                "description": description,
                "storage_uri": storage_uri,
                "content_hash": digest,
                "needs_normalisation": True,
                "generic_pipeline_stage": "raw_archived",
                "batch_index": idx,
            }
            record = ingestion_job_service.add_raw_record(
                db=db,
                job=job,
                record_type=_generic_record_type(category, source_format),
                raw_payload=raw_payload,
                source_record_id=filename,
                storage_uri=storage_uri,
                content_hash=digest,
                validation_status="pending",
                normalised_payload=normalised_payload,
            )
            ingestion_job_service.update_progress(db, job, current=idx + 1, total=len(files), seen_delta=1, loaded_delta=1)
            loaded += 1
            record_ids.append(str(record.record_id))
        except Exception as exc:
            failed += 1
            errors.append(f"{upload_file.filename}: {str(exc)}")

    ingestion_job_service.mark_completed(db, job)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="generic_source_intake_batch",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="generic_source_intake_batch",
        result="completed",
        metadata={
            "job_id": str(job.job_id),
            "source_id": str(source.source_id),
            "files_loaded": loaded,
            "files_failed": failed,
            "source_category": category,
        },
    )
    db.commit()
    db.refresh(job)
    db.refresh(source)
    return {
        "message": f"Batch intake completed. {loaded} files loaded, {failed} failed.",
        "job": IngestionJobResponse.model_validate(job).model_dump(mode="json"),
        "source": _source_payload(source),
        "files_loaded": loaded,
        "files_failed": failed,
        "record_ids": record_ids,
        "errors": errors,
    }


@router.get("/data-quality/summary")
def get_data_quality_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return production_data_quality_service.data_quality_summary(db)


@router.post("/data-quality/remap-table-rows")
def remap_extracted_table_rows(
    limit: int = Query(default=5000, ge=1, le=50000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
) -> Dict[str, Any]:
    result = production_data_quality_service.remap_extracted_table_rows(db, limit=limit)
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="data_quality_remap",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="remap_extracted_table_rows",
        result="completed",
        metadata=result,
    )
    db.commit()
    return result


@router.get(
    "/records/review",
    response_model=List[RawRecordResponse],
)
def list_records_for_review(
    source_id: UUID | None = None,
    job_id: UUID | None = None,
    status_filter: str | None = Query(default=None),
    source_category: str | None = Query(default=None),
    record_type: str | None = Query(default=None),
    low_confidence: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(RawIngestionRecord)
    if source_category:
        query = query.join(DataSource, RawIngestionRecord.source_id == DataSource.source_id).filter(
            DataSource.source_category == source_category
        )
    if source_id:
        query = query.filter(RawIngestionRecord.source_id == source_id)
    if job_id:
        query = query.filter(RawIngestionRecord.job_id == job_id)
    if record_type:
        query = query.filter(RawIngestionRecord.record_type == record_type)
    if status_filter:
        query = query.filter(RawIngestionRecord.validation_status == status_filter)
    else:
        query = query.filter(
            RawIngestionRecord.validation_status.in_(
                ["failed", "warning", "invalid", "skipped", "noise", "unmatched", "pending"]
            )
        )
    records = query.order_by(RawIngestionRecord.created_at.desc()).limit(limit).all()
    if low_confidence:
        records = [
            record for record in records
            if float((record.normalised_payload or {}).get("confidence_score") or 1) < 0.6
            or float((record.normalised_payload or {}).get("quality_score") or 1) < 0.6
        ]
    for record in records:
        setattr(record, "source_category", record.source.source_category if record.source else None)
        setattr(record, "source_name", record.source.name if record.source else None)
    return records


@router.post(
    "/records/{record_id}/review",
    response_model=RejectedRecordReviewResponse,
)
def review_ingestion_record(
    record_id: UUID,
    payload: RejectedRecordReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    record = (
        db.query(RawIngestionRecord)
        .filter(RawIngestionRecord.record_id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Raw ingestion record not found",
        )

    metadata = dict((record.normalised_payload or {}).get("review_metadata") or {})
    metadata.update(
        {
            "reviewed_by": current_user.identity_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_note": payload.note,
            "review_status": payload.status,
        }
    )
    normalised = dict(record.normalised_payload or {})
    if payload.corrected_payload:
        normalised.update(payload.corrected_payload)
        metadata["corrected"] = True
    normalised["review_metadata"] = metadata
    record.normalised_payload = normalised
    record.validation_status = payload.status

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_record_review",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="review_ingestion_record",
        result=payload.status,
        metadata={"record_id": str(record_id), "note": payload.note},
    )
    db.commit()
    db.refresh(record)
    return {
        "record_id": record.record_id,
        "validation_status": record.validation_status,
        "normalised_payload": record.normalised_payload,
        "review_metadata": metadata,
    }


@router.get(
    "/jobs/{job_id}/tables",
    response_model=List[ExtractedTableResponse],
)
def list_job_tables(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = ingestion_job_service.get_job(db, job_id)

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    return (
        db.query(ExtractedTable)
        .filter(ExtractedTable.job_id == job.job_id)
        .order_by(
            ExtractedTable.source_file.asc(),
            ExtractedTable.page_number.asc(),
            ExtractedTable.table_index.asc(),
        )
        .limit(500)
        .all()
    )


@router.get(
    "/tables/{table_id}",
    response_model=ExtractedTableResponse,
)
def get_extracted_table(
    table_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = (
        db.query(ExtractedTable)
        .filter(ExtractedTable.table_id == table_id)
        .first()
    )

    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extracted table not found",
        )

    return table


@router.get(
    "/tables/{table_id}/rows",
    response_model=List[ExtractedTableRowResponse],
)
def list_extracted_table_rows(
    table_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    table = (
        db.query(ExtractedTable)
        .filter(ExtractedTable.table_id == table_id)
        .first()
    )

    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extracted table not found",
        )

    return (
        db.query(ExtractedTableRow)
        .filter(ExtractedTableRow.table_id == table.table_id)
        .order_by(ExtractedTableRow.row_number.asc())
        .limit(1000)
        .all()
    )


@router.post(
    "/statssa/jobs",
    response_model=StatsSAJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_statssa_job(
    payload: StatsSAJobRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if payload.end_year < payload.start_year:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_year must be greater than or equal to start_year",
        )

    connector = StatsSAQLFSConnector()
    source = connector.ensure_source(db)

    if not source.is_authorised:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="StatsSA source is not authorised",
        )

    active_job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.job_type == "statssa_qlfs",
            IngestionJob.status.in_(["queued", "running"]),
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A StatsSA ingestion job is already queued or running.",
                "job_id": str(active_job.job_id),
                "status": active_job.status,
                "progress_current": active_job.progress_current,
                "progress_total": active_job.progress_total,
            },
        )

    job = ingestion_job_service.create_job(
        db=db,
        source=source,
        job_type="statssa_qlfs",
        triggered_by=current_user.identity_id,
        parameters=payload.model_dump(),
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_job",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="start_statssa_ingestion",
        result="accepted",
        metadata={
            "job_id": str(job.job_id),
            "parameters": payload.model_dump(),
        },
    )

    db.commit()
    db.refresh(job)

    operational_job, _ = operational_job_service.enqueue(
        db=db,
        job_type="ingestion.statssa",
        requested_by=current_user.identity_id,
        parameters={
            "ingestion_job_id": str(job.job_id),
            **payload.model_dump(),
        },
    )

    return {
        "message": "StatsSA ingestion job accepted",
        "job": job,
        "operational_job": operational_job_service.to_dict(operational_job),
    }


@router.post(
    "/che/vitalstats/jobs",
    response_model=StatsSAJobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_che_vitalstats_job(
    payload: CHEVitalStatsJobRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if payload.end_year < payload.start_year:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="end_year must be greater than or equal to start_year",
        )

    connector = CHEVitalStatsConnector()
    source = connector.ensure_source(db)

    if not source.is_authorised:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CHE VitalStats source is not authorised",
        )

    active_job = (
        db.query(IngestionJob)
        .filter(
            IngestionJob.job_type == "che_vitalstats",
            IngestionJob.status.in_(["queued", "running"]),
        )
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "A CHE VitalStats ingestion job is already queued or running.",
                "job_id": str(active_job.job_id),
                "status": active_job.status,
                "progress_current": active_job.progress_current,
                "progress_total": active_job.progress_total,
            },
        )

    job = ingestion_job_service.create_job(
        db=db,
        source=source,
        job_type="che_vitalstats",
        triggered_by=current_user.identity_id,
        parameters=payload.model_dump(),
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="ingestion_job",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="ingestion.api",
        action="start_che_vitalstats_ingestion",
        result="accepted",
        metadata={
            "job_id": str(job.job_id),
            "parameters": payload.model_dump(),
        },
    )

    db.commit()
    db.refresh(job)

    operational_job, _ = operational_job_service.enqueue(
        db=db,
        job_type="ingestion.che_vitalstats",
        requested_by=current_user.identity_id,
        parameters={
            "ingestion_job_id": str(job.job_id),
            **payload.model_dump(),
        },
    )

    return {
        "message": "CHE VitalStats ingestion job accepted",
        "job": job,
        "operational_job": operational_job_service.to_dict(operational_job),
    }
