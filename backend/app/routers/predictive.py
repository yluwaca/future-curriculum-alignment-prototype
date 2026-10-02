# backend/app/routers/predictive.py

"""
Enterprise Predictive API Router for FUTURE Platform.

Provides:
- ETL ingestion
- curriculum alignment prediction
- labour-market forecasting
- SHAP explainability
- predictive model training
- analytics and monitoring
- predictive system status

Aligned with:
- FastAPI
- SQLAlchemy 2.0
- RBAC
- Predictive services
- Audit governance
"""

from __future__ import annotations

import logging
import os
import json
import hashlib

from datetime import datetime, timezone
from typing import Any, Optional
from typing import Dict

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)

from sqlalchemy.orm import Session

from app.core.dependencies import (
    get_current_user,
    require_role,
)

from app.db.session import (
    get_db,
)

from app.models.user import (
    User,
)

from app.schemas.predictive import (
    AlignmentRequest,
    AlignmentResponse,
    ForecastRequest,
    ForecastResponse,
    IngestRequest,
    IngestResponse,
    StatusResponse,
)

from app.services.audit_service import (
    AuditService,
)

from app.services.etl_pipeline import (
    ETLPipeline,
)

from app.services.model_service import (
    ModelService,
)
from app.core.model_loader import ModelLoadError
from app.services.model_evaluation_service import model_evaluation_service
from app.services.ml_recommendation_quality_service import ml_recommendation_quality_service
from app.services.model_dataset_snapshot_service import model_dataset_snapshot_service
from app.services.model_registry_service import (
    get_model_registry_service,
    ModelRegistryService,
)
from app.models.model_registry import ModelRegistryEntry
from app.services.operational_job_service import operational_job_service
from app.services.candidate_training_service import candidate_training_service
from app.services.model_lifecycle_coordinator import ModelLifecycleCoordinator

import numpy as np
from datetime import timedelta
from scipy import stats as scipy_stats

# =========================================================
# Logging
# =========================================================

logger = logging.getLogger(__name__)

# =========================================================
# Router
# =========================================================

router = APIRouter(
    prefix="/predictive",
    tags=["Predictive Analytics"],
)

# =========================================================
# Services
# =========================================================

etl_pipeline = ETLPipeline()

model_service = ModelService()
model_lifecycle_coordinator = ModelLifecycleCoordinator(model_service)

audit_service = AuditService()


def _prepare_registry_artifact(entry):
    """Verify registry integrity and load an artifact without serving it."""
    if not entry.artifact_checksum:
        raise HTTPException(
            status_code=400,
            detail="Registry artifact has no checksum",
        )
    if not os.path.isfile(entry.artifact_path):
        raise HTTPException(
            status_code=400,
            detail="Registry artifact is missing",
        )
    digest = hashlib.sha256()
    with open(entry.artifact_path, "rb") as artifact:
        for block in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != entry.artifact_checksum:
        raise HTTPException(
            status_code=400,
            detail="Registry artifact checksum does not match",
        )
    try:
        return model_service.prepare_artifact_activation(
            entry.model_type,
            entry.artifact_path,
        )
    except ModelLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/registry/runtime-continuity")
async def registry_runtime_continuity(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST", "ANALYST")
    ),
):
    """Compare registry-designated active entries with serving identities."""
    registry_svc = get_model_registry_service(db)
    models = {}
    overall = "passed"
    runtime_identities = getattr(model_service, "active_registry_models", {})
    for model_type in ("xgboost", "lstm"):
        active = registry_svc.get_active_model(model_type)
        runtime = runtime_identities.get(model_type)
        matches = (
            active is None and runtime is None
        ) or (
            active is not None
            and runtime is not None
            and str(active.entry_id) == str(runtime.get("entry_id"))
        )
        if not matches:
            overall = "failed"
        models[model_type] = {
            "status": "matched" if matches else "mismatch",
            "registry_entry_id": str(active.entry_id) if active else None,
            "registry_model_version": active.model_version if active else None,
            "runtime": runtime,
        }
    return {
        "status": overall,
        "models": models,
        "startup_restoration": getattr(
            request.app.state,
            "model_restart_restoration",
            {"status": "not_recorded_in_current_process"},
        ),
        "single_active_constraint": "uq_model_registry_one_active_type",
    }



@router.get("/model-readiness")
async def model_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return model maturity gates and baseline-vs-ML readiness.
    """
    import json
    import os

    result = model_evaluation_service.readiness(db)

    metrics_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "models",
        "model_metrics.json",
    )
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path) as f:
                metrics = json.load(f)
            if metrics.get("xgboost") and metrics["xgboost"].get("trained_at"):
                result["xgboost_last_trained"] = metrics["xgboost"]["trained_at"]
            if metrics.get("lstm") and metrics["lstm"].get("trained_at"):
                result["lstm_last_trained"] = metrics["lstm"]["trained_at"]
        except Exception as exc:
            logger.warning("[PREDICTIVE] Failed to read metrics file: %s", exc)

    return result


@router.get("/model-metrics")
async def model_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return stored training metrics (F1, AUC, RMSE, SMAPE, CV folds).
    """
    import json
    import os

    metrics_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "models",
        "model_metrics.json",
    )
    if not os.path.exists(metrics_path):
        return {"xgboost": None, "lstm": None}
    with open(metrics_path) as f:
        metrics = json.load(f)
    # Training evidence and promotion readiness are separate concerns.
    # Preserve completed candidate metrics even when readiness gates block promotion.
    metrics["readiness"] = model_evaluation_service.readiness(db)
    # Legacy failed-job presentation fix: the metrics file is written by the trainer
    # before candidate_training_service attaches the registry identity, so lifecycle
    # state / dataset mode / experimental-UAT disclosure are absent from disk. Join the
    # persisted dataset_fingerprint to the model registry at read time (non-destructive:
    # model_metrics.json is never rewritten) so the successful candidate and its exact
    # fingerprint are unambiguous, while historical failed jobs remain visible in the
    # operational-job history and the registry keeps every prior candidate append-only.
    metrics = _attach_registry_identity(db, metrics)
    return metrics


def _attach_registry_identity(db: Session, metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich persisted xgboost/lstm metrics with their registry candidate identity.

    Matches on the exact ``dataset_fingerprint`` recorded with the metrics so the
    displayed candidate is provably the one registered from that locked dataset. Falls
    back to the latest candidate of the same type only when the fingerprint is absent.
    Never mutates stored metrics on disk and never hides historical failures.
    """
    registry = get_model_registry_service(db)
    for model_type in ("xgboost", "lstm"):
        block = metrics.get(model_type)
        if not isinstance(block, dict) or not block:
            continue
        fingerprint = block.get("dataset_fingerprint")
        entry = None
        if fingerprint:
            entry = (
                db.query(ModelRegistryEntry)
                .filter(
                    ModelRegistryEntry.model_type == model_type,
                    ModelRegistryEntry.dataset_fingerprint == fingerprint,
                )
                .order_by(ModelRegistryEntry.trained_at.desc())
                .first()
            )
        if entry is None:
            entry = registry.get_latest_candidate(model_type)
        if entry is None:
            block["registry_identity"] = {
                "matched": False,
                "reason": "No registry candidate matches this metrics fingerprint.",
            }
            continue
        matched_on = "dataset_fingerprint" if (fingerprint and entry.dataset_fingerprint == fingerprint) else "latest_candidate_fallback"
        entry_metrics = entry.metrics or {}
        block["registry_identity"] = {
            "matched": True,
            "matched_on": matched_on,
            "registry_entry_id": str(entry.entry_id),
            "model_version": entry.model_version,
            "lifecycle_state": entry.lifecycle_state,
            "is_active": entry.is_active == 1,
            "dataset_fingerprint": entry.dataset_fingerprint,
            "fingerprint_matches_metrics": bool(fingerprint and entry.dataset_fingerprint == fingerprint),
            "snapshot_id": str(entry.snapshot_id) if entry.snapshot_id else None,
            "trained_at": entry.trained_at.isoformat() if entry.trained_at else None,
            "dataset_mode": entry_metrics.get("dataset_mode"),
            "experimental_uat": entry_metrics.get("experimental_uat"),
            "label_provenance": entry_metrics.get("label_provenance"),
            "promotion_required": entry_metrics.get("promotion_required"),
            "reviewed_label_snapshot_version": entry_metrics.get("reviewed_label_snapshot_version"),
        }
        # Surface the honest disclosure at the top level of the block too, so the panel
        # cannot present an experimental UAT candidate as independently validated.
        if entry_metrics.get("dataset_mode"):
            block.setdefault("dataset_mode", entry_metrics.get("dataset_mode"))
        if entry_metrics.get("experimental_uat") is not None:
            block.setdefault("experimental_uat", entry_metrics.get("experimental_uat"))
        block.setdefault("lifecycle_state", entry.lifecycle_state)
        block.setdefault("registry_entry_id", str(entry.entry_id))
    return metrics




@router.get("/dataset-snapshots/latest")
async def latest_dataset_snapshot(
    model_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return the latest reproducible dataset snapshot metadata.
    """
    snapshot = model_dataset_snapshot_service.latest_snapshot(db, model_type=model_type)
    return {"latest": model_dataset_snapshot_service.to_dict(snapshot) if snapshot else None}


@router.get("/dataset-snapshots")
async def list_dataset_snapshots(
    model_type: Optional[str] = None,
    limit: int = 25,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List recent reproducible dataset snapshots.
    """
    snapshots = model_dataset_snapshot_service.list_snapshots(db, model_type=model_type, limit=limit)
    return {"items": [model_dataset_snapshot_service.to_dict(item) for item in snapshots]}


@router.post("/dataset-snapshots")
async def create_dataset_snapshot(
    model_type: str = "general",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    """
    Create a reproducible dataset preparation snapshot without training a model.
    """
    snapshot = model_dataset_snapshot_service.create_snapshot(
        db=db,
        model_type=model_type,
        actor_id=current_user.identity_id,
        notes="Manual Phase 3 dataset snapshot",
    )
    audit_service.log_event(
        db=db,
        user_id=current_user.identity_id,
        action="MODEL_DATASET_SNAPSHOT_CREATE",
        resource="model_dataset_snapshot",
        details={
            "snapshot_id": str(snapshot.snapshot_id),
            "model_type": snapshot.model_type,
            "dataset_fingerprint": snapshot.dataset_fingerprint,
        },
    )
    return model_dataset_snapshot_service.to_dict(snapshot)


@router.post("/model-evaluation/run")
async def run_model_evaluation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    """
    Persist a model readiness/evaluation report in the generated report archive.
    """
    result = model_evaluation_service.persist_evaluation_report(
        db=db,
        actor_id=current_user.identity_id,
    )
    audit_service.log_event(
        db=db,
        user_id=current_user.identity_id,
        action="MODEL_READINESS_EVALUATION",
        resource="model_registry",
        details={"report_id": result.get("report_id")},
    )
    return result


@router.get("/forecast/quality")
async def forecast_recommendation_quality(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return forecast evaluation, model registry, recommendation ranking,
    and explainability quality metrics.
    """
    return ml_recommendation_quality_service.quality_summary(db)


@router.post("/forecast/recommendation-ranking/refresh")
async def refresh_recommendation_ranking(
    limit: int = 500,
    dry_run: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    """
    Recalculate recommendation priority scores using current forecast,
    gap, demand evidence, and confidence factors.
    """
    result = ml_recommendation_quality_service.refresh_recommendation_ranking(
        db=db,
        limit=limit,
        dry_run=dry_run,
    )
    audit_service.log_event(
        db=db,
        user_id=current_user.identity_id,
        action="RECOMMENDATION_RANKING_REFRESH",
        resource="recommendation_ranker",
        details={"dry_run": dry_run, "recommendations_checked": result.get("recommendations_checked")},
    )
    return result


@router.post("/forecast/explainability-report")
async def generate_explainability_report(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    """
    Persist a model/recommendation quality and explainability report.
    """
    result = ml_recommendation_quality_service.persist_explainability_report(
        db=db,
        actor_id=current_user.identity_id,
    )
    audit_service.log_event(
        db=db,
        user_id=current_user.identity_id,
        action="EXPLAINABILITY_REPORT",
        resource="model_registry",
        details={"report_id": result.get("report_id")},
    )
    return result





# =========================================================
# ETL INGESTION
# =========================================================


@router.post(
    "/ingest",
    response_model=IngestResponse,
)
async def ingest_data(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "DATA_SCIENTIST")),
):
    """
    Execute predictive ETL ingestion.
    """

    logger.info(
        "[API] ETL ingestion started "
        "(user=%s)",
        current_user.identity_id,
    )

    try:

        result = (
            etl_pipeline
            .process_etl_pipeline(
                db=db,
                curriculum_data=request.curriculum_data,
                job_data=request.job_posting_data,
                force_reprocess=request.force_reprocess,
            )
        )

        # -------------------------------------------------
        # Audit
        # -------------------------------------------------

        audit_service.log_event(
            db=db,
            user_id=current_user.identity_id,
            action="ETL_INGEST",
            resource="predictive_pipeline",
            details=result,
        )

        # -------------------------------------------------
        # Background Retraining
        # -------------------------------------------------

        background_tasks.add_task(
            trigger_background_training
        )

        return IngestResponse(
            message=(
                "ETL ingestion completed successfully."
            ),
            curriculum_ingested=result.get(
                "curriculum_ingested",
                0,
            ),
            job_postings_ingested=result.get(
                "job_postings_ingested",
                0,
            ),
            timestamp=datetime.now(timezone.utc),
        )

    except Exception as exc:

        logger.exception(
            "[API] ETL ingestion failed"
        )

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

# =========================================================
# ALIGNMENT PREDICTION
# =========================================================


@router.post(
    "/align",
    response_model=AlignmentResponse,
)
async def predict_alignment(
    request: AlignmentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Predict curriculum alignment.
    """

    logger.info(
        "[API] Alignment prediction "
        "(module=%s)",
        request.module_code,
    )

    try:

        result = (
            model_service
            .run_alignment_prediction(
                db=db,
                curriculum_module_code=request.module_code,
                region=request.region,
            )
        )

        audit_service.log_event(
            db=db,
            user_id=current_user.identity_id,
            action="ALIGNMENT_PREDICTION",
            resource=request.module_code,
            details={
                "alignment_score": result.get(
                    "alignment_score"
                ),
                "is_aligned": result.get(
                    "is_aligned"
                ),
            },
        )

        return AlignmentResponse(
            **result
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )

    except Exception as exc:

        logger.exception(
            "[API] Alignment prediction failed"
        )

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

# =========================================================
# FORECASTING
# =========================================================


@router.post(
    "/forecast",
    response_model=ForecastResponse,
)
async def forecast_demand(
    request: ForecastRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run labour-market demand forecast.
    """

    logger.info(
        "[API] Forecast request "
        "(module=%s)",
        request.module_code,
    )

    try:

        result = (
            model_service
            .run_demand_forecast(
                db=db,
                curriculum_module_code=request.module_code,
                forecast_horizon=request.forecast_horizon,
                region=request.region,
            )
        )

        audit_service.log_event(
            db=db,
            user_id=current_user.identity_id,
            action="DEMAND_FORECAST",
            resource=request.module_code,
            details={
                "forecast_horizon": (
                    request.forecast_horizon
                ),
            },
        )

        return ForecastResponse(
            **result
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=404,
            detail=str(exc),
        )

    except RuntimeError as exc:

        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )

    except Exception as exc:

        logger.exception(
            "[API] Forecast failed"
        )

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

# =========================================================
# SYSTEM STATUS
# =========================================================


@router.get(
    "/status",
    response_model=StatusResponse,
)
async def get_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):
    """
    Get predictive system status.
    """

    try:

        result = (
            model_service
            .get_model_status(
                db=db
            )
        )

        return StatusResponse(
            **result,
            message=(
                "Predictive services operational."
            ),
            last_etl_run=None,
        )

    except Exception as exc:

        logger.exception(
            "[API] Status check failed"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

# =========================================================
# XGBOOST TRAINING
# =========================================================


@router.get(
    "/train/xgboost/readiness",
)
async def xgboost_train_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(
            "ADMIN",
            "DATA_SCIENTIST",
        )
    ),
):
    report = candidate_training_service.readiness(db)
    return {
        "status": "ready" if report["ready"] else "blocked",
        "message": report.get("note") if report["ready"] else " ".join(report["blocked_reasons"]),
        "readiness": report,
    }


@router.post(
    "/train/xgboost",
)
async def train_xgboost(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(
            "ADMIN",
            "DATA_SCIENTIST",
        )
    ),
):
    readiness = candidate_training_service.readiness(db)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "XGBoost candidate training is not ready yet",
                "readiness": readiness,
            },
        )
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="model.train.xgboost",
        requested_by=current_user.identity_id,
        parameters={"model_type": "xgboost", "candidate_only": True},
        max_attempts=1,
    )
    return {
        "message": "XGBoost candidate training accepted",
        "accepted": created,
        "coalesced": not created,
        "operational_job": operational_job_service.to_dict(job),
        "readiness": readiness,
        "metrics": {"status": "queued", "model_type": "xgboost", "experimental_uat": readiness["experimental_uat"]},
    }

# =========================================================
# LSTM TRAINING
# =========================================================


@router.post(
    "/train/lstm",
)
async def train_lstm(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(
            "ADMIN",
            "DATA_SCIENTIST",
        )
    ),
):
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="model.train.lstm",
        requested_by=current_user.identity_id,
        parameters={"model_type": "lstm", "candidate_only": True},
        max_attempts=1,
    )
    return {
        "message": "LSTM candidate training accepted",
        "accepted": created,
        "coalesced": not created,
        "operational_job": operational_job_service.to_dict(job),
        "metrics": {"status": "queued", "model_type": "lstm"},
    }

# =========================================================
# BACKGROUND TRAINING
# =========================================================


def trigger_background_training(
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Background retraining hook with auto-retraining triggers.

    Paper triggers:
      1. F1-score drop >5% from baseline (0.84)
      2. KS-test concept drift (p<0.05)
      3. Quarterly interval
      4. >15% external benchmark divergence
    """

    logger.info("[BACKGROUND] Checking retraining triggers")

    result = {
        "triggered": False,
        "reasons": [],
        "checks": {},
    }

    # 1. Load current metrics
    metrics_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "models",
        "model_metrics.json",
    )
    current_metrics = {}
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path) as f:
                current_metrics = json.load(f)
        except Exception as exc:
            logger.warning("[BACKGROUND] Could not load metrics: %s", exc)

    # 2. F1-score drop >5% from baseline (paper baseline F1=0.84)
    baseline_f1 = 0.84
    xgb_metrics = current_metrics.get("xgboost", {})
    current_f1 = xgb_metrics.get("f1_score")
    f1_check = {"baseline": baseline_f1, "current": current_f1}
    if current_f1 is not None and current_f1 < baseline_f1 * 0.95:
        f1_check["triggered"] = True
        result["reasons"].append(
            f"F1 score {current_f1:.4f} dropped >5% from baseline {baseline_f1}"
        )
    else:
        f1_check["triggered"] = False
    result["checks"]["f1_drop"] = f1_check

    # 3. KS-test concept drift on forecast residuals
    ks_check = {"triggered": False, "p_value": None}
    if db is not None:
        try:
            from sqlalchemy import text as sql_text
            from app.models.forecast import Forecast

            recent = (
                db.query(Forecast)
                .order_by(Forecast.created_at.desc())
                .limit(50)
                .all()
            )
            if len(recent) >= 10:
                residuals = [
                    abs(f.forecast_value - f.baseline_value)
                    for f in recent
                    if f.forecast_value is not None and f.baseline_value is not None
                ]
                if len(residuals) >= 10:
                    half = len(residuals) // 2
                    early = residuals[:half]
                    late = residuals[half:]
                    _, p_value = scipy_stats.ks_2samp(early, late)
                    ks_check["p_value"] = round(p_value, 4)
                    ks_check["triggered"] = p_value < 0.05
                    if ks_check["triggered"]:
                        result["reasons"].append(
                            f"KS-test detected concept drift (p={p_value:.4f} < 0.05)"
                        )
        except Exception as exc:
            logger.warning("[BACKGROUND] KS-test failed: %s", exc)
    result["checks"]["ks_drift"] = ks_check

    # 4. Quarterly interval check
    trained_at_str = xgb_metrics.get("trained_at")
    quarterly_check = {"triggered": False, "last_trained": trained_at_str}
    if trained_at_str:
        try:
            trained_at = datetime.fromisoformat(trained_at_str)
            if datetime.now(timezone.utc) - (trained_at if trained_at.tzinfo else trained_at.replace(tzinfo=timezone.utc)) > timedelta(days=90):
                quarterly_check["triggered"] = True
                result["reasons"].append(
                    f"Quarterly retraining interval reached "
                    f"(last trained: {trained_at_str})"
                )
        except Exception as exc:
            logger.warning("[PREDICTIVE] Failed to parse trained_at timestamp: %s", exc)
    result["checks"]["quarterly"] = quarterly_check

    # 5. >15% external benchmark divergence
    benchmark_check = {"triggered": False, "divergence_pct": None}
    oihd_correlation = xgb_metrics.get("oihd_correlation")
    if oihd_correlation is not None:
        divergence = (1.0 - float(oihd_correlation)) * 100
        benchmark_check["divergence_pct"] = round(divergence, 2)
        benchmark_check["triggered"] = divergence > 15.0
        if benchmark_check["triggered"]:
            result["reasons"].append(
                f"External benchmark divergence {divergence:.1f}% > 15% threshold"
            )
    result["checks"]["benchmark_divergence"] = benchmark_check

    result["triggered"] = any(
        c.get("triggered", False) for c in result["checks"].values()
    )
    logger.info(
        "[BACKGROUND] Retraining %s (reasons=%s)",
        "TRIGGERED" if result["triggered"] else "SKIPPED",
        result["reasons"],
    )

    # Future integrations:
    # - Celery
    # - APScheduler
    # - Redis queues
    # - MLFlow
    # - Kubernetes jobs

    return result


# =========================================================
# MODEL REGISTRY
# =========================================================


@router.get("/registry")
async def list_registry_entries(
    model_type: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST", "ANALYST"),
    ),
):
    """
    List model registry entries with optional filters.
    """
    try:
        registry_svc = get_model_registry_service(db)
        entries = registry_svc.list_entries(
            model_type=model_type,
            state=state,
            limit=limit,
        )
        # The registry list drives a compact selector in Model Lab.  Returning
        # every candidate's complete metrics, folds, SHAP evidence and model
        # card made this endpoint grow to hundreds of kilobytes and caused the
        # browser to fall back to an empty registry after training.  Full
        # evidence remains available from the single-entry endpoint below and
        # from the dedicated metrics endpoint.
        compact_entries = []
        for entry in entries:
            item = registry_svc.to_dict(entry)
            for heavy_field in (
                "metrics",
                "cv_folds",
                "baseline_comparison",
                "fairness_assessment",
                "explainability",
                "model_card",
            ):
                item.pop(heavy_field, None)
            compact_entries.append(item)
        return {
            "entries": compact_entries,
            "count": len(entries),
        }
    except Exception as exc:
        logger.exception("[API] Failed to list registry entries")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/registry/active/{model_type}")
async def get_active_model(
    model_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST", "ANALYST", "VIEWER"),
    ),
):
    """
    Get the current active model for a given type.
    """
    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_active_model(model_type)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"No active model for type '{model_type}'",
        )
    return registry_svc.to_dict(entry)


@router.get("/registry/{entry_id}")
async def get_registry_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST", "ANALYST", "VIEWER"),
    ),
):
    """
    Get a specific registry entry by ID.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")
    return registry_svc.to_dict(entry)


@router.post("/registry/{entry_id}/evaluate")
async def evaluate_registry_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST"),
    ),
):
    """
    Mark a candidate as evaluated.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    try:
        entry = registry_svc.update_state(
            uid, "evaluated", actor_id=current_user.identity_id
        )
        return {
            "message": f"Model {entry.model_version} marked as evaluated",
            "entry": registry_svc.to_dict(entry),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))



@router.post("/registry/{entry_id}/test-evidence")
async def record_registry_test_evidence(
    entry_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST"),
    ),
):
    """
    Attach automated test evidence to a candidate before approval/promotion.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")

    tests = {
        "status": payload.get("status", "passed"),
        "summary": payload.get("summary", "Focused automated tests passed."),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "recorded_by": current_user.identity_id,
        "details": payload.get("details", {}),
    }
    metrics = dict(entry.metrics or {})
    metrics["automated_tests"] = tests
    entry.metrics = metrics
    can, gates = registry_svc.can_approve(entry)
    entry.promotion_gates = gates
    db.commit()
    db.refresh(entry)
    audit_service.log_event(
        db=db,
        user_id=current_user.identity_id,
        action="RECORD_MODEL_TEST_EVIDENCE",
        resource="model_registry",
        details={"entry_id": str(uid), "tests": tests, "can_approve": can},
    )
    return {
        "message": "Automated test evidence recorded",
        "can_approve": can,
        "entry": registry_svc.to_dict(entry),
        "gates": gates,
    }


@router.post("/registry/{entry_id}/approve")
async def approve_registry_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN"),
    ),
):
    """
    Approve a candidate for promotion.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")

    can, gates = registry_svc.can_approve(entry)
    if not can:
        failed = [k for k, v in gates.items() if not v["passed"]]
        raise HTTPException(
            status_code=400,
            detail=f"Promotion gates failed: {failed}",
        )

    try:
        entry = registry_svc.update_state(
            uid, "approved", actor_id=current_user.identity_id
        )
        return {
            "message": f"Model {entry.model_version} approved for promotion",
            "entry": registry_svc.to_dict(entry),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/registry/{entry_id}/promote")
async def promote_registry_entry(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN"),
    ),
):
    """
    Promote a candidate to active.
    Deactivates the previously active model of the same type.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")

    can, gates = registry_svc.can_promote(entry)
    if not can:
        failed = [k for k, v in gates.items() if not v["passed"]]
        raise HTTPException(
            status_code=400,
            detail=f"Promotion gates failed: {failed}",
        )

    try:
        entry = model_lifecycle_coordinator.promote(
            db=db,
            entry_id=uid,
            actor_id=current_user.identity_id,
        )
        audit_service.log_event(
            db=db,
            user_id=current_user.identity_id,
            action="PROMOTE_MODEL",
            resource="model_registry",
            details={"entry_id": str(uid), "model_version": entry.model_version},
        )
        return {
            "message": f"Model {entry.model_version} promoted to active",
            "entry": registry_svc.to_dict(entry),
        }
    except ModelLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/registry/{entry_id}/reject")
async def reject_registry_entry(
    entry_id: str,
    reason: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST"),
    ),
):
    """
    Reject a candidate.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    try:
        entry = registry_svc.update_state(
            uid, "rejected",
            actor_id=current_user.identity_id,
            reason=reason,
        )
        return {
            "message": f"Model {entry.model_version} rejected",
            "entry": registry_svc.to_dict(entry),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/registry/{entry_id}/gates")
async def check_promotion_gates_endpoint(
    entry_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "DATA_SCIENTIST", "ANALYST"),
    ),
):
    """
    Check promotion gates for a registry entry.
    """
    from uuid import UUID as UUIDType
    try:
        uid = UUIDType(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    registry_svc = get_model_registry_service(db)
    entry = registry_svc.get_entry(uid)
    if not entry:
        raise HTTPException(status_code=404, detail="Registry entry not found")

    can, gates = registry_svc.can_promote(entry)
    entry.promotion_gates = gates
    db.commit()
    return {
        "entry_id": str(uid),
        "model_version": entry.model_version,
        "can_promote": can,
        "gates": gates,
    }


@router.post("/registry/rollback/{model_type}")
async def rollback_model(
    model_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN"),
    ),
):
    """
    Rollback to the previously active model of the given type.
    """
    registry_svc = get_model_registry_service(db)
    try:
        restored = model_lifecycle_coordinator.rollback(
            db=db,
            model_type=model_type,
            actor_id=current_user.identity_id,
        )
        audit_service.log_event(
            db=db,
            user_id=current_user.identity_id,
            action="ROLLBACK_MODEL",
            resource="model_registry",
            details={"model_type": model_type, "restored_version": restored.model_version},
        )
        return {
            "message": f"Rolled back {model_type} to {restored.model_version}",
            "entry": registry_svc.to_dict(restored),
        }
    except ModelLoadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))








