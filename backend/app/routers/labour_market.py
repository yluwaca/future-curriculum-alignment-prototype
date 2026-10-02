from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.core.tenant_scope import scope_query
from app.db.session import get_db
from app.models.data_source import DataSource
from app.models.ingestion_job import IngestionJob
from app.models.job_posting import JobPosting
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.models.pipeline_run import PipelineRun
from app.models.skill_mapping import SkillMapping
from app.models.user import User
from app.schemas.labour_market import (
    JobAdvertUploadResponse,
    JobPostingResponse,
    LabourMarketSkillPipelineRequest,
    LabourMarketSkillPipelineResponse,
    LabourMarketSkillSignalRequest,
    LabourMarketSkillSignalResponse,
    LabourMarketSignalResponse,
    LabourMarketTrendResponse,
    SignalGenerateRequest,
    SignalGenerateResponse,
    TrendNormaliseRequest,
    TrendNormaliseResponse,
    TrendSummaryResponse,
)
from app.schemas.pipeline import PipelineRunResponse
from app.services.audit_service import log_audit_event
from app.services.ingestion.adzuna_governance import (
    ADZUNA_ATTRIBUTION_NOTE,
    ADZUNA_PERMISSION,
)
from app.services.structured_log import log_structured

logger = logging.getLogger(__name__)

from app.services.ingestion.statssa_service import (
    start_statssa_job,
    get_job
)
from app.services.ingestion.job_advert_file_connector import job_advert_file_connector
from app.services.labour_market_skill_pipeline_service import labour_market_skill_pipeline_service
from app.services.labour_market_trend_service import labour_market_trend_service

router = APIRouter(
    prefix="/labour-market",
    tags=["Labour Market"]
)


ADZUNA_TRIAL_SOURCE_LABEL = "ADZUNA_TRIAL_NOT_EMPIRICAL"
ADZUNA_PIPELINE_RUN_KEY = "adzuna_labour_market_skill_pipeline_v1"
ADZUNA_SIGNAL_RUN_KEY = "adzuna_labour_market_signal_generation_v1"


def _trial_scope(sources: List[str]) -> dict:
    """Return source-scope metadata when a run is scoped to the Adzuna source.

    The stable source key, acquisition label (``ADZUNA_TRIAL_NOT_EMPIRICAL``)
    and acquisition mode (``live_trial_uat``) are preserved for provenance and
    idempotent re-imports. Since 2026-09-10 the source carries written academic
    research permission, so the metadata now reports the permission record and
    attribution requirement instead of claiming trial data is ineligible.
    """
    if not sources or ADZUNA_TRIAL_SOURCE_LABEL not in sources:
        return {}
    permission = ADZUNA_PERMISSION
    return {
        "source_label": ADZUNA_TRIAL_SOURCE_LABEL,
        "acquisition_mode": "live_trial_uat",
        "evidence_class": "trial_uat",
        "unit": "normalised_posting_count",
        "permission_status": permission["permission_status"],
        "permission_received_at": permission["permission_received_at"],
        "permission_scope": permission["permission_scope"],
        "empirical_use_permitted": True,
        "attribution_required": permission["attribution_required"],
        "attribution_url": permission["attribution_url"],
        "attribution_note": ADZUNA_ATTRIBUTION_NOTE,
        "evidence_path": permission["evidence_path"],
        "representativeness_note": (
            "Adzuna South Africa vacancy data used under written academic research "
            "permission (2026-09-10). Attribution to https://www.adzuna.co.za is "
            "required in any thesis, publication, research or examiner package. "
            "Historical pre-permission rows keep their original trial/UAT metadata."
        ),
    }


def _adzuna_ingestion_job_ids(db: Session) -> List[str]:
    rows = (
        db.query(IngestionJob.job_id)
        .filter(IngestionJob.job_type.like("adzuna%"))
        .order_by(IngestionJob.created_at.desc())
        .all()
    )
    return [str(row[0]) for row in rows]


# Legacy display units written by older pipeline versions. These are stale,
# source-specific labels that leaked an internal acquisition channel ("trial",
# "public_service") into a user-facing measurement unit. They are remapped to a
# neutral, correct unit at DISPLAY time only; the stored row and its provenance
# (source_counts, evidence_scope, representativeness_note, permission record) are
# never rewritten, so the evidence dossier retains the true origin.
_LEGACY_DISPLAY_UNIT_MAP = {
    "trial_job_postings": "job_postings",
    "public_service_job_postings": "job_postings",
}


def _display_unit(raw_unit: Optional[str]) -> Dict[str, Any]:
    """Return a neutral display unit plus the retained raw value and provenance flag.

    Non-destructive: never mutates the stored signal. When a legacy unit is
    remapped the original value is preserved under ``raw_unit`` and flagged with
    ``normalised_from_legacy_unit`` so the dossier can show the true source unit.
    """
    if raw_unit in _LEGACY_DISPLAY_UNIT_MAP:
        return {
            "unit": _LEGACY_DISPLAY_UNIT_MAP[raw_unit],
            "raw_unit": raw_unit,
            "normalised_from_legacy_unit": True,
        }
    return {
        "unit": raw_unit,
        "raw_unit": raw_unit,
        "normalised_from_legacy_unit": False,
    }


def _persist_pipeline_run(
    db: Session,
    *,
    pipeline_key: str,
    tenant_id,
    actor_id: str,
    parameters: dict,
    summary: dict,
):
    now = datetime.now(timezone.utc)
    run = PipelineRun(
        pipeline_key=pipeline_key,
        tenant_id=tenant_id,
        run_scope="shared",
        status="completed",
        triggered_by=actor_id,
        parameters=parameters,
        summary=summary,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    return run


@router.post("/extract/statssa")
def extract_statssa(
    current_user: User = Depends(get_current_user),
):
    job_id = start_statssa_job()
    return {
        "message": "StatsSA extraction started",
        "job_id": job_id
    }


@router.get("/job/{job_id}")
def job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
):
    job = get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        **job,
    }


@router.post(
    "/jobs/upload",
    response_model=JobAdvertUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_job_adverts(
    file: UploadFile = File(...),
    source_label: str | None = Form(default=None),
    default_region: str = Form(default="South Africa"),
    default_country: str = Form(default="ZA"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or "job_adverts.csv"
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in {"csv", "xlsx", "json", "txt", "pdf"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only CSV, XLSX, JSON, TXT, and PDF job advert uploads are supported",
        )
    try:
        return job_advert_file_connector.ingest_upload(
            db=db,
            file_bytes=await file.read(),
            original_filename=filename,
            actor_id=current_user.identity_id,
            source_label=source_label,
            default_region=default_region,
            default_country=default_country,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/jobs",
    response_model=List[JobPostingResponse],
)
def list_job_postings(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(JobPosting)
        .order_by(JobPosting.posted_date.desc(), JobPosting.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


@router.post(
    "/jobs/skill-pipeline",
    response_model=LabourMarketSkillPipelineResponse,
)
def run_job_skill_pipeline(
    payload: LabourMarketSkillPipelineRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    sources = payload.sources or None
    result = labour_market_skill_pipeline_service.run(
        db=db,
        limit=payload.limit,
        offset=payload.offset,
        actor_id=current_user.identity_id,
        sources=sources,
    )
    run = _persist_pipeline_run(
        db=db,
        pipeline_key=(ADZUNA_PIPELINE_RUN_KEY if sources and ADZUNA_TRIAL_SOURCE_LABEL in sources
                      else "labour_market_skill_pipeline_v1"),
        tenant_id=current_user.tenant_id,
        actor_id=current_user.identity_id,
        parameters={"limit": payload.limit, "offset": payload.offset, "sources": list(sources) if sources else None},
        summary=result,
    )
    db.flush()
    ingestion_job_ids = _adzuna_ingestion_job_ids(db) if sources else []
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="labour_market_skill_pipeline",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="labour_market.jobs",
        action="run_job_skill_pipeline",
        result="success",
        metadata={"run_id": str(run.pipeline_run_id), "sources": list(sources) if sources else None, **result},
    )
    db.commit()
    result.update(
        {
            "run_id": str(run.pipeline_run_id),
            "sources": list(sources) if sources else [],
            "ingestion_job_ids": ingestion_job_ids,
            "trial_scope": _trial_scope(list(sources) if sources else []),
        }
    )
    log_structured(
        logger,
        "labour_market_pipeline",
        action="pipeline_run_completed",
        run_id=str(run.pipeline_run_id),
        sources=list(sources) if sources else [],
        postings_seen=(result.get("cleaned") or {}).get("postings_seen"),
        cleaned_created=(result.get("cleaned") or {}).get("cleaned_created"),
        aliases_created=(result.get("mappings") or {}).get("aliases_created"),
        mappings_created=(result.get("mappings") or {}).get("mappings_created"),
        mappings_skipped=(result.get("mappings") or {}).get("mappings_skipped"),
        signals_created=(result.get("signals") or {}).get("signals_created"),
        evidence_created=(result.get("evidence") or {}).get("evidence_created"),
    )
    return result


@router.post(
    "/jobs/skill-pipeline/signals",
    response_model=LabourMarketSkillSignalResponse,
)
def generate_job_skill_pipeline_signals(
    payload: LabourMarketSkillSignalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    sources = payload.sources or None
    source_list = list(sources) if sources else []

    mapping_query = (
        db.query(func.count(SkillMapping.mapping_id))
        .join(JobPosting, SkillMapping.source_entity_id == JobPosting.posting_id)
        .filter(
            SkillMapping.source_domain == "labour_market",
            SkillMapping.source_entity_type == "job_posting",
        )
    )
    if sources:
        mapping_query = mapping_query.filter(JobPosting.source.in_(source_list))
    mappings_considered = int(mapping_query.scalar() or 0)
    mappings_approved_used = int(
        mapping_query.filter(SkillMapping.mapping_status == "approved").scalar() or 0
    )

    signals = labour_market_skill_pipeline_service.generate_job_skill_signals(
        db=db, limit=payload.limit, sources=sources
    )
    evidence = labour_market_skill_pipeline_service.generate_job_skill_demand_evidence(
        db=db, limit=payload.limit, sources=sources
    )

    result = {
        "mappings_considered": mappings_considered,
        "mappings_approved_used": mappings_approved_used,
        "signals_seen": int(signals.get("signals_seen", 0)),
        "signals_created": int(signals.get("signals_created", 0)),
        "signals_updated": int(signals.get("signals_updated", 0)),
        "evidence_seen": int(evidence.get("signals_seen", 0)),
        "evidence_created": int(evidence.get("evidence_created", 0)),
        "evidence_skipped": int(evidence.get("evidence_skipped", 0)),
        "promotion_gate": signals.get("promotion_gate", "approved_labour_mappings_only"),
    }

    run = _persist_pipeline_run(
        db=db,
        pipeline_key=(ADZUNA_SIGNAL_RUN_KEY if sources and ADZUNA_TRIAL_SOURCE_LABEL in sources
                      else "labour_market_signal_generation_v1"),
        tenant_id=current_user.tenant_id,
        actor_id=current_user.identity_id,
        parameters={"limit": payload.limit, "sources": source_list or None},
        summary=result,
    )
    db.flush()
    ingestion_job_ids = _adzuna_ingestion_job_ids(db) if sources else []
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="labour_market_signal",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="labour_market.jobs",
        action="generate_job_skill_signals",
        result="success",
        metadata={"run_id": str(run.pipeline_run_id), "sources": source_list, **result},
    )
    db.commit()
    result.update(
        {
            "sources": source_list,
            "ingestion_job_ids": ingestion_job_ids,
            "trial_scope": _trial_scope(source_list),
            "run_id": str(run.pipeline_run_id),
        }
    )
    log_structured(
        logger,
        "labour_market_signal_generation",
        action="signal_generation_completed",
        run_id=str(run.pipeline_run_id),
        sources=source_list,
        mappings_considered=result.get("mappings_considered"),
        mappings_approved_used=result.get("mappings_approved_used"),
        signals_seen=result.get("signals_seen"),
        signals_created=result.get("signals_created"),
        signals_updated=result.get("signals_updated"),
        evidence_created=result.get("evidence_created"),
        promotion_gate=result.get("promotion_gate"),
    )
    return result


@router.get(
    "/jobs/skill-pipeline/signals",
)
def list_job_skill_pipeline_trial_signals(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Demand Outlook technical-UAT view: approved Adzuna job-skill demand signals."""
    rows = (
        db.query(LabourMarketSignal)
        .filter(
            LabourMarketSignal.method == "job_skill_demand_v1",
            LabourMarketSignal.signal_metadata["evidence_scope"].astext == "adzuna_trial_uat_not_empirical",
        )
        .order_by(LabourMarketSignal.demand_score.desc(), LabourMarketSignal.evidence_count.desc())
        .limit(limit)
        .all()
    )
    return {
        "total_signal_count": len(rows),
        "trial_scope": _trial_scope([ADZUNA_TRIAL_SOURCE_LABEL]),
        "ingestion_job_ids": _adzuna_ingestion_job_ids(db),
        "signals": [
            {
                "signal_id": str(row.signal_id),
                "skill_name": row.dimension_value,
                "canonical_key": row.canonical_key,
                "demand_value": row.demand_score,
                "normalised_value": row.normalised_value,
                "period": f"{row.year} {row.quarter}",
                "year": row.year,
                "quarter": row.quarter,
                "evidence_count": row.evidence_count,
                **_display_unit(row.unit),
                "confidence_score": row.confidence_score,
                "source_scope": (row.signal_metadata or {}).get("evidence_scope"),
                "source_counts": (row.signal_metadata or {}).get("source_counts", {}),
                "representativeness_note": (row.signal_metadata or {}).get("representativeness_note"),
                "empirical_use_permitted": (row.signal_metadata or {}).get("empirical_use_permitted", False),
            }
            for row in rows
        ],
    }


@router.get(
    "/jobs/skill-pipeline/runs",
    response_model=List[PipelineRunResponse],
)
def list_skill_pipeline_runs(
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        scope_query(
            db.query(PipelineRun),
            PipelineRun,
            current_user,
        )
        .filter(
            PipelineRun.pipeline_key.in_(
                [ADZUNA_PIPELINE_RUN_KEY, ADZUNA_SIGNAL_RUN_KEY, "labour_market_skill_pipeline_v1", "labour_market_signal_generation_v1"]
            )
        )
        .order_by(PipelineRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post(
    "/trends/normalise",
    response_model=TrendNormaliseResponse,
)
def normalise_trends(
    payload: TrendNormaliseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = labour_market_trend_service.normalise_from_cleaned_records(
        db=db,
        job_id=str(payload.job_id) if payload.job_id else None,
        limit=payload.limit,
        actor_id=current_user.identity_id,
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="labour_market_trend",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="labour_market.trends",
        action="normalise_cleaned_trends",
        result="success",
        metadata=result,
    )
    db.commit()
    return result


@router.get(
    "/trends/summary",
    response_model=TrendSummaryResponse,
)
def trend_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return labour_market_trend_service.summary(db)


@router.post(
    "/signals/generate",
    response_model=SignalGenerateResponse,
)
def generate_signals(
    payload: SignalGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = labour_market_trend_service.generate_signals(
        db=db,
        limit=payload.limit,
        actor_id=current_user.identity_id,
    )

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="labour_market_signal",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="labour_market.signals",
        action="generate_canonical_signals",
        result="success",
        metadata=result,
    )
    db.commit()
    return result


@router.get(
    "/trends",
    response_model=List[LabourMarketTrendResponse],
)
def list_trends(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(LabourMarketTrend)
        .order_by(LabourMarketTrend.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


@router.get(
    "/signals",
    response_model=List[LabourMarketSignalResponse],
)
def list_signals(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(LabourMarketSignal)
        .order_by(LabourMarketSignal.demand_score.desc(), LabourMarketSignal.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _ingestion_job_summary(job: Optional[IngestionJob]) -> Optional[dict]:
    if not job:
        return None
    return {
        "job_id": str(job.job_id),
        "job_type": job.job_type,
        "status": job.status,
        "records_seen": job.records_seen,
        "records_loaded": job.records_loaded,
        "records_failed": job.records_failed,
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
        "failure_category": job.failure_category,
        "failure_stage": job.failure_stage,
        "error_summary": job.error_summary,
    }


def _pipeline_run_summary(run: Optional[PipelineRun]) -> Optional[dict]:
    if not run:
        return None
    return {
        "run_id": str(run.pipeline_run_id),
        "pipeline_key": run.pipeline_key,
        "status": run.status,
        "completed_at": _iso(run.completed_at),
        "summary": run.summary or {},
    }


@router.get(
    "/jobs/provider-readiness-report",
)
def provider_readiness_report(
    sources: Optional[str] = Query(
        default=None,
        description="Comma-separated provider source keys; defaults to all current-jobs sources.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Read-only provider readiness report for labour-market operations.

    Reports, per registered current-jobs source: ingestion job history,
    saved posting totals, labour-market mapping status counts, and the
    latest pipeline/signal-generation runs. The endpoint only reads rows it
    is already entitled to see (tenant scoped) and cannot mutate state.
    """
    source_keys = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    query = scope_query(db.query(DataSource), DataSource, current_user).filter(
        DataSource.source_category == "current_jobs"
    )
    if source_keys:
        query = query.filter(DataSource.source_key.in_(source_keys))
    data_sources = query.order_by(DataSource.source_key.asc()).all()

    signal_run_keys = [ADZUNA_SIGNAL_RUN_KEY, "labour_market_signal_generation_v1"]
    pipeline_run_keys = [ADZUNA_PIPELINE_RUN_KEY, "labour_market_skill_pipeline_v1"]

    pipeline_runs = (
        scope_query(db.query(PipelineRun), PipelineRun, current_user)
        .filter(PipelineRun.pipeline_key.in_(pipeline_run_keys))
        .order_by(PipelineRun.created_at.desc(), PipelineRun.pipeline_run_id.desc())
        .all()
    )
    signal_runs = (
        scope_query(db.query(PipelineRun), PipelineRun, current_user)
        .filter(PipelineRun.pipeline_key.in_(signal_run_keys))
        .order_by(PipelineRun.created_at.desc(), PipelineRun.pipeline_run_id.desc())
        .all()
    )
    signals_total = int(db.query(func.count(LabourMarketSignal.signal_id)).scalar() or 0)

    rows = []
    for source in data_sources:
        source_ids = db.query(JobPosting.posting_id).filter(JobPosting.source_id == source.source_id)
        postings_total = int(
            db.query(func.count(JobPosting.posting_id)).filter(JobPosting.source_id == source.source_id).scalar() or 0
        )
        jobs = (
            db.query(IngestionJob)
            .filter(IngestionJob.source_id == source.source_id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.job_id.desc())
            .all()
        )
        status_rows = (
            db.query(SkillMapping.mapping_status, func.count(SkillMapping.mapping_id))
            .filter(
                SkillMapping.source_domain == "labour_market",
                SkillMapping.source_entity_type == "job_posting",
                SkillMapping.source_entity_id.in_(source_ids),
            )
            .group_by(SkillMapping.mapping_status)
            .all()
        )
        by_status = {status: int(count) for status, count in status_rows}
        mappings_reviewed = int(
            db.query(func.count(SkillMapping.mapping_id))
            .filter(
                SkillMapping.source_domain == "labour_market",
                SkillMapping.source_entity_type == "job_posting",
                SkillMapping.source_entity_id.in_(source_ids),
                SkillMapping.reviewed_by.isnot(None),
            )
            .scalar()
            or 0
        )
        rows.append(
            {
                "source": {
                    "source_key": source.source_key,
                    "name": source.name,
                    "source_type": source.source_type,
                    "source_category": source.source_category,
                    "connector_type": source.connector_type,
                    "is_authorised": bool(source.is_authorised),
                    "status": source.status,
                    "consecutive_failures": source.consecutive_failures,
                    "last_success_at": _iso(source.last_success_at),
                    "last_failure_at": _iso(source.last_failure_at),
                    "permission": (source.config or {}).get("permission"),
                    "attribution_note": (source.config or {}).get("attribution_note"),
                },
                "ingestion": {
                    "job_count": len(jobs),
                    "latest_job": _ingestion_job_summary(jobs[0] if jobs else None),
                },
                "postings": {"total": postings_total},
                "mappings": {
                    "candidate": by_status.get("candidate", 0),
                    "approved": by_status.get("approved", 0),
                    "rejected": by_status.get("rejected", 0),
                    "merged": by_status.get("merged", 0),
                    "needs_review": by_status.get("needs_review", 0),
                    "reviewed_count": mappings_reviewed,
                },
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_name": "labour_market_provider_readiness",
        "report_version": "v1",
        "scope": {
            "sources": [s.source_key for s in data_sources],
            "filter": source_keys,
        },
        "rows": rows,
        "global": {
            "pipeline_runs_total": len(pipeline_runs),
            "latest_pipeline_run": _pipeline_run_summary(pipeline_runs[0] if pipeline_runs else None),
            "signal_runs_total": len(signal_runs),
            "latest_signal_run": _pipeline_run_summary(signal_runs[0] if signal_runs else None),
            "signals_total": signals_total,
        },
    }
