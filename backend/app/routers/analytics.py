"""
Analytics and recommendation endpoints.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role, resolve_user_roles
from app.core.permissions import require_permission
from app.db.session import get_db
from app.models.alignment_score import AlignmentScore
from app.models.data_lineage_event import DataLineageEvent
from app.models.forecast import Forecast
from app.models.generated_report import GeneratedReport
from app.models.labour_market_signal import LabourMarketSignal
from app.models.labour_market_trend import LabourMarketTrend
from app.models.recommendation import Recommendation
from app.models.recommendation_explanation import RecommendationExplanation
from app.models.recommendation_feedback import RecommendationFeedback
from app.models.recommendation_review import RecommendationReview
from app.models.recommendation_status_history import RecommendationStatusHistory
from app.models.skill import Skill
from app.models.skill_demand_evidence import SkillDemandEvidence
from app.models.user import User
from app.schemas.analytics import (
    AlignmentScoreResponse,
    AnalyticsSummaryResponse,
    ForecastResponse,
    GeneratedReportDetailResponse,
    GeneratedReportResponse,
    GenerateAnalyticsRequest,
    GenerateAnalyticsResponse,
    RecommendationExplanationResponse,
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationDossierResponse,
    RecommendationLineageResponse,
    RecommendationResponse,
    RecommendationReviewRequest,
    RecommendationReviewResponse,
    RecommendationStatusHistoryResponse,
    CommitteeDecisionRequest,
)
from app.services.analytics_recommendation_service import analytics_recommendation_service
from app.services.audit_service import log_audit_event
from app.services.ingestion.adzuna_governance import ADZUNA_ATTRIBUTION_NOTE
from app.services.recommendation_review_service import recommendation_review_service
from app.services.recommendation_governance_service import recommendation_governance_service


router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
)


def payload_hash(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(jsonable_encoder(payload), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def demand_evidence_uses_adzuna(demand_evidence: List[Dict[str, Any]]) -> bool:
    """True when any demand-evidence row originates from the Adzuna source."""
    for row in demand_evidence:
        meta = row.get("evidence_metadata") or {}
        if meta.get("attribution_url"):
            return True
        summary = str(meta.get("source_summary") or "").upper()
        if "ADZUNA" in summary:
            return True
    return False


def recommendation_actionability(recommendation) -> Dict[str, Any]:
    """Derive whether a recommendation is actionable (approval-eligible).

    A recommendation with zero resolvable labour-market evidence is non-actionable:
    it can be rejected but never approved, and it is marked with a reason rather than
    deleted. Computed at read time from stored metadata so existing zero-evidence items
    are transparently flagged without any destructive rewrite. Already-decided rows
    (approved/rejected/modified) keep their recorded outcome and are not re-gated.
    """
    meta = recommendation.recommendation_metadata or {}
    evidence_status = meta.get("evidence_status")
    demand_count = meta.get("skill_demand_evidence_count")
    labour_count = meta.get("labour_evidence_count")
    zero_evidence = evidence_status == "insufficient_evidence" or (
        not demand_count and not labour_count and not meta.get("top_demand_evidence")
    )
    status_value = recommendation.status
    decided = status_value in {"approved", "rejected", "modified_pending_review", "superseded"}
    if zero_evidence and not decided:
        return {
            "actionable": False,
            "non_actionable_reason": (
                "Zero resolvable labour-market evidence (evidence_status="
                f"{evidence_status or 'insufficient_evidence'}; skill_demand_evidence_count="
                f"{demand_count or 0}, labour_evidence_count={labour_count or 0}). "
                "Approval is blocked until demand-evidence generation re-supports this "
                "recommendation; it may be rejected. Retained non-actionable, never deleted."
            ),
        }
    return {"actionable": True, "non_actionable_reason": None}


def _recommendation_response_dict(recommendation) -> Dict[str, Any]:
    """Serialize a Recommendation ORM row plus derived actionability (non-destructive)."""
    actionability = recommendation_actionability(recommendation)
    return {
        "recommendation_id": recommendation.recommendation_id,
        "alignment_id": recommendation.alignment_id,
        "forecast_id": recommendation.forecast_id,
        "skill_id": recommendation.skill_id,
        "document_id": recommendation.document_id,
        "version_id": recommendation.version_id,
        "recommendation_type": recommendation.recommendation_type,
        "title": recommendation.title,
        "description": recommendation.description,
        "priority": recommendation.priority,
        "priority_score": recommendation.priority_score,
        "confidence_score": recommendation.confidence_score,
        "status": recommendation.status,
        "recommendation_metadata": recommendation.recommendation_metadata,
        "actionable": actionability["actionable"],
        "non_actionable_reason": actionability["non_actionable_reason"],
        "created_at": recommendation.created_at,
        "updated_at": recommendation.updated_at,
    }


def build_recommendation_dossier(
    recommendation_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    recommendation = (
        db.query(Recommendation)
        .filter(Recommendation.recommendation_id == recommendation_id)
        .first()
    )
    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    skill = (
        db.query(Skill)
        .filter(Skill.skill_id == recommendation.skill_id)
        .first()
        if recommendation.skill_id
        else None
    )
    alignment = (
        db.query(AlignmentScore)
        .filter(AlignmentScore.alignment_id == recommendation.alignment_id)
        .first()
        if recommendation.alignment_id
        else None
    )
    forecast = (
        db.query(Forecast)
        .filter(Forecast.forecast_id == recommendation.forecast_id)
        .first()
        if recommendation.forecast_id
        else None
    )
    explanations = (
        db.query(RecommendationExplanation)
        .filter(RecommendationExplanation.recommendation_id == recommendation_id)
        .order_by(RecommendationExplanation.created_at.asc())
        .all()
    )
    demand_evidence = (
        db.query(SkillDemandEvidence)
        .filter(SkillDemandEvidence.skill_id == recommendation.skill_id)
        .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
        .limit(20)
        .all()
        if recommendation.skill_id
        else []
    )
    demand_evidence_payload = []
    for item in demand_evidence:
        payload = jsonable_encoder(item)
        evidence_meta = dict(item.evidence_metadata or {})
        signal = item.signal
        signal_meta = dict(signal.signal_metadata or {}) if signal else {}
        source_value = (
            evidence_meta.get("source_type")
            or evidence_meta.get("data_source")
            or evidence_meta.get("source")
            or evidence_meta.get("provider")
            or evidence_meta.get("source_name")
            or signal_meta.get("source_type")
            or signal_meta.get("data_source")
            or signal_meta.get("source")
            or signal_meta.get("provider")
            or signal_meta.get("source_name")
            or (signal.source_summary if signal else None)
            or (signal.signal_type if signal else None)
        )
        provenance_value = (
            evidence_meta.get("acquisition_mode")
            or evidence_meta.get("provenance")
            or signal_meta.get("acquisition_mode")
            or signal_meta.get("provenance")
            or (signal.method if signal else None)
        )
        if source_value:
            payload["source_type"] = str(source_value)
            payload["data_source"] = str(source_value)
        if provenance_value:
            evidence_meta.setdefault("provenance", str(provenance_value))
        if signal:
            evidence_meta.setdefault("signal_id", str(signal.signal_id))
            evidence_meta.setdefault("signal_year", signal.year)
            evidence_meta.setdefault("signal_quarter", signal.quarter)
        payload["evidence_metadata"] = evidence_meta
        demand_evidence_payload.append(payload)
    reviews = (
        db.query(RecommendationReview)
        .filter(RecommendationReview.recommendation_id == recommendation_id)
        .order_by(RecommendationReview.created_at.asc())
        .all()
    )
    feedback = (
        db.query(RecommendationFeedback)
        .filter(RecommendationFeedback.recommendation_id == recommendation_id)
        .order_by(RecommendationFeedback.created_at.asc())
        .all()
    )
    history = (
        db.query(RecommendationStatusHistory)
        .filter(RecommendationStatusHistory.recommendation_id == recommendation_id)
        .order_by(RecommendationStatusHistory.created_at.asc())
        .all()
    )

    canonical_keys = sorted(
        {
            item.evidence_metadata.get("canonical_key")
            for item in demand_evidence
            if item.evidence_metadata.get("canonical_key")
        }
    )
    evidence_summary = {
        "skill_demand_evidence_count": recommendation.recommendation_metadata.get("skill_demand_evidence_count", len(demand_evidence)),
        "skill_demand_score": recommendation.recommendation_metadata.get("skill_demand_score"),
        "canonical_signal_keys": recommendation.recommendation_metadata.get("canonical_signal_keys", canonical_keys),
        "top_demand_evidence": recommendation.recommendation_metadata.get("top_demand_evidence", []),
        "review_count": len(reviews),
        "feedback_count": len(feedback),
        "status_history_count": len(history),
    }
    actionability = recommendation_actionability(recommendation)

    return {
        "recommendation": recommendation,
        "skill": skill,
        "alignment": alignment,
        "forecast": forecast,
        "explanations": explanations,
        "demand_evidence": demand_evidence_payload,
        "reviews": reviews,
        "feedback": feedback,
        "status_history": history,
        "evidence_summary": evidence_summary,
        "actionable": actionability["actionable"],
        "non_actionable_reason": actionability["non_actionable_reason"],
    }


def lineage_node(node_id: str, node_type: str, label: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "metadata": metadata or {},
    }


def lineage_edge(source: str, target: str, relation: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "relation": relation,
        "metadata": metadata or {},
    }


def build_recommendation_lineage(
    recommendation_id: UUID,
    db: Session,
) -> Dict[str, Any]:
    recommendation = (
        db.query(Recommendation)
        .filter(Recommendation.recommendation_id == recommendation_id)
        .first()
    )
    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lineage_event_rows: List[DataLineageEvent] = []
    seen_nodes = set()
    seen_edges = set()
    seen_events = set()

    def add_node(node: Dict[str, Any]) -> None:
        if node["id"] not in seen_nodes:
            nodes.append(node)
            seen_nodes.add(node["id"])

    def add_edge(edge: Dict[str, Any]) -> None:
        key = (edge["source"], edge["target"], edge["relation"])
        if key not in seen_edges:
            edges.append(edge)
            seen_edges.add(key)

    def add_events(events: List[DataLineageEvent]) -> None:
        for event in events:
            event_id = str(event.lineage_id)
            if event_id not in seen_events:
                lineage_event_rows.append(event)
                seen_events.add(event_id)

    recommendation_node_id = f"recommendation:{recommendation.recommendation_id}"
    add_node(lineage_node(
        recommendation_node_id,
        "recommendation",
        recommendation.title,
        {
            "status": recommendation.status,
            "priority": recommendation.priority,
            "priority_score": recommendation.priority_score,
        },
    ))

    if recommendation.skill_id:
        skill = db.query(Skill).filter(Skill.skill_id == recommendation.skill_id).first()
        skill_node_id = f"skill:{recommendation.skill_id}"
        add_node(lineage_node(
            skill_node_id,
            "skill",
            skill.name if skill else str(recommendation.skill_id),
            {"skill_key": skill.skill_key if skill else None},
        ))
        add_edge(lineage_edge(skill_node_id, recommendation_node_id, "supports_recommendation"))

    if recommendation.alignment_id:
        alignment = db.query(AlignmentScore).filter(AlignmentScore.alignment_id == recommendation.alignment_id).first()
        alignment_node_id = f"alignment:{recommendation.alignment_id}"
        add_node(lineage_node(
            alignment_node_id,
            "alignment_score",
            "Curriculum alignment score",
            {
                "alignment_score": alignment.alignment_score if alignment else None,
                "gap_score": alignment.gap_score if alignment else None,
            },
        ))
        add_edge(lineage_edge(alignment_node_id, recommendation_node_id, "explains_gap"))

    if recommendation.forecast_id:
        forecast = db.query(Forecast).filter(Forecast.forecast_id == recommendation.forecast_id).first()
        forecast_node_id = f"forecast:{recommendation.forecast_id}"
        add_node(lineage_node(
            forecast_node_id,
            "forecast",
            "Skill demand forecast",
            {
                "forecast_value": forecast.forecast_value if forecast else None,
                "method": forecast.method if forecast else None,
                "confidence_score": forecast.confidence_score if forecast else None,
            },
        ))
        add_edge(lineage_edge(forecast_node_id, recommendation_node_id, "informs_priority"))

    demand_evidence = (
        db.query(SkillDemandEvidence)
        .filter(SkillDemandEvidence.skill_id == recommendation.skill_id)
        .order_by(SkillDemandEvidence.demand_score.desc(), SkillDemandEvidence.confidence_score.desc())
        .limit(20)
        .all()
        if recommendation.skill_id
        else []
    )

    for evidence in demand_evidence:
        evidence_node_id = f"skill_demand_evidence:{evidence.evidence_id}"
        add_node(lineage_node(
            evidence_node_id,
            "skill_demand_evidence",
            evidence.matched_context,
            {
                "demand_score": evidence.demand_score,
                "confidence_score": evidence.confidence_score,
                "match_method": evidence.match_method,
            },
        ))
        add_edge(lineage_edge(evidence_node_id, recommendation_node_id, "supports"))
        if recommendation.skill_id:
            add_edge(lineage_edge(f"skill:{recommendation.skill_id}", evidence_node_id, "matched_to"))

        signal = db.query(LabourMarketSignal).filter(LabourMarketSignal.signal_id == evidence.signal_id).first()
        if not signal:
            continue
        signal_node_id = f"labour_market_signal:{signal.signal_id}"
        add_node(lineage_node(
            signal_node_id,
            "labour_market_signal",
            signal.canonical_name,
            {
                "canonical_key": signal.canonical_key,
                "dimension_type": signal.dimension_type,
                "dimension_value": signal.dimension_value,
                "demand_score": signal.demand_score,
                "source_summary": signal.source_summary,
            },
        ))
        add_edge(lineage_edge(signal_node_id, evidence_node_id, "generates_evidence"))

        trend_ids = (signal.signal_metadata or {}).get("trend_ids", [])[:10]
        for trend_id in trend_ids:
            try:
                trend_uuid = UUID(str(trend_id))
            except ValueError:
                continue
            trend = db.query(LabourMarketTrend).filter(LabourMarketTrend.trend_id == trend_uuid).first()
            if not trend:
                continue
            trend_node_id = f"labour_market_trend:{trend.trend_id}"
            add_node(lineage_node(
                trend_node_id,
                "labour_market_trend",
                trend.indicator_name,
                {
                    "year": trend.year,
                    "quarter": trend.quarter,
                    "value": trend.value,
                    "dimension_type": trend.dimension_type,
                    "dimension_value": trend.dimension_value,
                    "source_file": trend.source_file,
                },
            ))
            add_edge(lineage_edge(trend_node_id, signal_node_id, "aggregated_into_signal"))

            if trend.job_id:
                job_node_id = f"ingestion_job:{trend.job_id}"
                add_node(lineage_node(job_node_id, "ingestion_job", str(trend.job_id)))
                add_edge(lineage_edge(job_node_id, trend_node_id, "produced_trend"))
                add_events(
                    db.query(DataLineageEvent)
                    .filter(DataLineageEvent.job_id == trend.job_id)
                    .order_by(DataLineageEvent.event_time.asc())
                    .limit(50)
                    .all()
                )
            if trend.raw_record_id:
                raw_node_id = f"raw_ingestion_record:{trend.raw_record_id}"
                add_node(lineage_node(raw_node_id, "raw_ingestion_record", str(trend.raw_record_id)))
                add_edge(lineage_edge(raw_node_id, trend_node_id, "source_record"))
                add_events(
                    db.query(DataLineageEvent)
                    .filter(DataLineageEvent.input_record_id == trend.raw_record_id)
                    .order_by(DataLineageEvent.event_time.asc())
                    .limit(20)
                    .all()
                )

    lineage_events = [
        {
            "lineage_id": str(event.lineage_id),
            "event_time": event.event_time.isoformat() if event.event_time else None,
            "job_id": str(event.job_id) if event.job_id else None,
            "source_id": str(event.source_id) if event.source_id else None,
            "processing_stage": event.processing_stage,
            "source_system": event.source_system,
            "transformation_description": event.transformation_description,
            "metadata": event.lineage_metadata,
        }
        for event in lineage_event_rows
    ]

    return {
        "recommendation_id": recommendation.recommendation_id,
        "skill_id": recommendation.skill_id,
        "lineage_nodes": nodes,
        "lineage_edges": edges,
        "lineage_events": lineage_events,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "lineage_event_count": len(lineage_events),
            "demand_evidence_count": len(demand_evidence),
            "trace_depth": "recommendation_to_ingestion",
        },
    }


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_recommendation_service.summary(db)


@router.get("/skill-gaps")
def skill_gap_summary(
    version_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return analytics_recommendation_service.skill_gap_summary(
        db=db,
        version_id=version_id,
        limit=limit,
    )

@router.get("/skill-gaps/{skill_id}/evidence")
def skill_gap_evidence(
    skill_id: UUID,
    version_id: Optional[UUID] = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    detail = analytics_recommendation_service.skill_gap_evidence_detail(
        db=db,
        skill_id=skill_id,
        version_id=version_id,
        limit=limit,
    )
    if not detail.get("found", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail.get("message", "Skill not found"),
        )
    return detail


@router.post("/generate", response_model=GenerateAnalyticsResponse)
def generate_analytics(
    request: GenerateAnalyticsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analytics_recommendation_service.generate_all(
        db=db,
        version_id=request.version_id,
        horizon_periods=request.horizon_periods,
    )


@router.get("/alignment-scores", response_model=List[AlignmentScoreResponse])
def list_alignment_scores(
    version_id: Optional[UUID] = None,
    limit: int = Query(default=100, ge=1, le=500),
    include_metadata: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AlignmentScore)
    if version_id:
        query = query.filter(AlignmentScore.version_id == version_id)
    rows = query.order_by(AlignmentScore.created_at.desc()).limit(limit).all()
    if include_metadata:
        return rows
    return [
        {
            "alignment_id": row.alignment_id,
            "document_id": row.document_id,
            "version_id": row.version_id,
            "score_type": row.score_type,
            "alignment_score": row.alignment_score,
            "gap_score": row.gap_score,
            "curriculum_skill_count": row.curriculum_skill_count,
            "labour_market_skill_count": row.labour_market_skill_count,
            "overlapping_skill_count": row.overlapping_skill_count,
            "missing_skill_count": row.missing_skill_count,
            "confidence_score": row.confidence_score,
            "model_version": row.model_version,
            "status": row.status,
            "score_metadata": {},
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


@router.get("/forecasts", response_model=List[ForecastResponse])
def list_forecasts(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.query(Forecast).order_by(Forecast.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    skill_ids = [row.skill_id for row in rows if row.skill_id]
    skills = {
        skill.skill_id: skill
        for skill in db.query(Skill).filter(Skill.skill_id.in_(skill_ids)).all()
    } if skill_ids else {}
    # Read-time provenance backfill: forecasts generated before the source/provenance
    # dossier was baked into forecast_payload still must explain query/source, ingestion
    # job IDs, observation range, record counts, dedup rule, snapshot fingerprint, method,
    # baselines, uncertainty and limitations. The dossier is computed once from the CURRENT
    # evidence base and clearly flagged as read-time (not generation-time) so it is never
    # mistaken for an immutable point-in-time record. Non-destructive: stored rows are not
    # rewritten. Newer forecasts keep their own baked generation-time dossier.
    try:
        current_dossier = analytics_recommendation_service._forecast_provenance_dossier(db)
    except Exception:  # pragma: no cover - provenance must never break the forecast list
        current_dossier = None
    result = []
    for row in rows:
        payload = dict(row.forecast_payload or {})
        if current_dossier and not payload.get("provenance"):
            payload["provenance"] = {
                **current_dossier,
                "provenance_basis": "read_time_current_evidence_base",
                "provenance_note": (
                    "This forecast predates generation-time provenance capture; the dossier "
                    "reflects the current evidence base at read time, not the exact inputs at "
                    "generation. Newer forecasts carry an immutable generation-time dossier."
                ),
            }
        elif payload.get("provenance"):
            payload["provenance"].setdefault("provenance_basis", "generation_time")
        result.append({
            "forecast_id": row.forecast_id,
            "skill_id": row.skill_id,
            "skill_name": skills.get(row.skill_id).name if row.skill_id in skills else None,
            "skill_key": skills.get(row.skill_id).skill_key if row.skill_id in skills else None,
            "forecast_type": row.forecast_type,
            "horizon_periods": row.horizon_periods,
            "baseline_value": row.baseline_value,
            "forecast_value": row.forecast_value,
            "trend_direction": row.trend_direction,
            "confidence_score": row.confidence_score,
            "method": row.method,
            "forecast_payload": payload,
            "explanation": row.explanation,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        })
    return result

@router.get("/reports", response_model=List[GeneratedReportResponse])
def list_generated_reports(
    report_type: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(GeneratedReport)
    if report_type:
        query = query.filter(GeneratedReport.report_type == report_type)
    return (
        query
        .order_by(GeneratedReport.created_at.desc())
        .limit(min(max(limit, 1), 500))
        .all()
    )


@router.get("/reports/{report_id}", response_model=GeneratedReportDetailResponse)
def get_generated_report(
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = (
        db.query(GeneratedReport)
        .filter(GeneratedReport.report_id == report_id)
        .first()
    )
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Generated report not found",
        )
    return report


@router.get("/recommendations", response_model=List[RecommendationResponse])
def list_recommendations(
    status: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Recommendation)
    if status:
        query = query.filter(Recommendation.status == status)
    rows = (
        query
        .order_by(Recommendation.priority_score.desc(), Recommendation.created_at.desc())
        .limit(min(max(limit, 1), 500))
        .all()
    )
    return [_recommendation_response_dict(row) for row in rows]


@router.get("/recommendations/grouped", response_model=Dict[str, Any])
def grouped_recommendations(
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return jsonable_encoder(
        analytics_recommendation_service.grouped_recommendations(
            db=db,
            status=status,
            limit=limit,
        )
    )


@router.get("/recommendation-governance/readiness", response_model=Dict[str, Any])
def recommendation_governance_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return recommendation_governance_service.readiness(db)


@router.post("/recommendation-governance/committee-pack", response_model=GeneratedReportResponse)
def generate_recommendation_committee_pack(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("ADMIN", "ANALYST", "DATA_SCIENTIST", "CURRICULUM_APPROVER")
    ),
):
    return recommendation_governance_service.generate_pack(db, current_user.identity_id)


@router.post("/recommendations/{recommendation_id}/committee-decision", response_model=Dict[str, Any])
def record_recommendation_committee_decision(
    recommendation_id: UUID,
    request: CommitteeDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("CURRICULUM_APPROVER")),
    _academic_permission: User = Depends(require_permission("recommendation.academic_approve")),
):
    return jsonable_encoder(recommendation_governance_service.decide(
        db, recommendation_id, request.evidence_report_id,
        current_user.identity_id, current_user.identity_type,
        request.decision, request.rationale, request.committee_name,
        request.meeting_reference, request.conditions,
    ))


@router.get(
    "/recommendations/{recommendation_id}/dossier",
    response_model=RecommendationDossierResponse,
)
def recommendation_dossier(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_recommendation_dossier(recommendation_id=recommendation_id, db=db)


@router.get(
    "/recommendations/{recommendation_id}/lineage",
    response_model=RecommendationLineageResponse,
)
def recommendation_lineage(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_recommendation_lineage(recommendation_id=recommendation_id, db=db)


@router.get(
    "/recommendations/{recommendation_id}/dossier/report",
    response_model=Dict[str, Any],
)
def recommendation_dossier_report(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dossier = RecommendationDossierResponse.model_validate(
        build_recommendation_dossier(recommendation_id=recommendation_id, db=db)
    ).model_dump(mode="json")
    recommendation = dossier["recommendation"]
    skill = dossier.get("skill") or {}
    alignment = dossier.get("alignment") or {}
    forecast = dossier.get("forecast") or {}
    evidence_summary = dossier.get("evidence_summary") or {}

    report = {
        "report_type": "recommendation_evidence_dossier",
        "generated_for": current_user.identity_id,
        "recommendation_id": recommendation["recommendation_id"],
        "executive_summary": {
            "title": recommendation["title"],
            "status": recommendation["status"],
            "priority": recommendation["priority"],
            "priority_score": recommendation["priority_score"],
            "confidence_score": recommendation["confidence_score"],
            "skill": skill.get("name"),
            "skill_key": skill.get("skill_key"),
            "alignment_score": alignment.get("alignment_score"),
            "gap_score": alignment.get("gap_score"),
            "forecast_value": forecast.get("forecast_value"),
            "skill_demand_evidence_count": evidence_summary.get("skill_demand_evidence_count"),
            "canonical_signal_keys": evidence_summary.get("canonical_signal_keys", []),
        },
        "recommendation": recommendation,
        "skill": skill,
        "alignment": alignment,
        "forecast": forecast,
        "evidence_summary": evidence_summary,
        "explanations": dossier.get("explanations", []),
        "demand_evidence": dossier.get("demand_evidence", []),
        "governance": {
            "reviews": dossier.get("reviews", []),
            "feedback": dossier.get("feedback", []),
            "status_history": dossier.get("status_history", []),
        },
    }
    lineage = build_recommendation_lineage(recommendation_id=recommendation_id, db=db)
    report["lineage_summary"] = jsonable_encoder(lineage["summary"])
    report["lineage"] = jsonable_encoder(lineage)
    report["attribution"] = {
        "note": ADZUNA_ATTRIBUTION_NOTE,
        "url": "https://www.adzuna.co.za",
        "applies_to": "demand_evidence",
    } if demand_evidence_uses_adzuna(dossier.get("demand_evidence", [])) else None
    report_hash = payload_hash(report)
    generated_report = GeneratedReport(
        report_type="recommendation_evidence_dossier",
        source_entity_type="recommendation",
        source_entity_id=recommendation_id,
        generated_by=current_user.identity_id,
        status="generated",
        title=report["executive_summary"]["title"],
        summary=report["executive_summary"],
        payload=report,
        payload_hash=report_hash,
        format_hint="json",
        notes="Generated from recommendation dossier report endpoint.",
    )
    db.add(generated_report)
    db.flush()
    report["report_id"] = str(generated_report.report_id)
    report["payload_hash"] = report_hash

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="recommendation_report",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="recommendation.dossier",
        action="recommendation_dossier_report_generated",
        result="success",
        metadata={
            "recommendation_id": str(recommendation_id),
            "report_type": "recommendation_evidence_dossier",
            "report_id": str(generated_report.report_id),
            "payload_hash": report_hash,
        },
    )
    db.commit()
    return jsonable_encoder(report)


@router.get(
    "/recommendations/{recommendation_id}/explanations",
    response_model=List[RecommendationExplanationResponse],
)
def list_recommendation_explanations(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(RecommendationExplanation)
        .filter(RecommendationExplanation.recommendation_id == recommendation_id)
        .order_by(RecommendationExplanation.created_at.asc())
        .all()
    )


@router.post(
    "/recommendations/{recommendation_id}/approve",
    response_model=RecommendationReviewResponse,
)
def approve_recommendation(
    recommendation_id: UUID,
    request: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("CURRICULUM_APPROVER")),
    _academic_permission: User = Depends(require_permission("recommendation.academic_approve")),
):
    result = recommendation_review_service.review(
        db=db,
        recommendation_id=recommendation_id,
        decision="approve",
        reviewer_id=current_user.identity_id,
        reviewer_type=current_user.identity_type,
        reason=request.reason,
        feedback_comment=request.feedback_comment,
        feedback_rating=request.feedback_rating,
        metadata=request.metadata,
        evidence_reviewed=request.evidence_reviewed,
        evidence_context=request.evidence_context,
        submitted_recommendation_id=request.recommendation_id,
        submitted_decision=request.decision,
        reviewer_roles=sorted(resolve_user_roles(current_user)),
    )
    return result["review"]


@router.post(
    "/recommendations/{recommendation_id}/reject",
    response_model=RecommendationReviewResponse,
)
def reject_recommendation(
    recommendation_id: UUID,
    request: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("CURRICULUM_APPROVER")),
    _academic_permission: User = Depends(require_permission("recommendation.academic_approve")),
):
    result = recommendation_review_service.review(
        db=db,
        recommendation_id=recommendation_id,
        decision="reject",
        reviewer_id=current_user.identity_id,
        reviewer_type=current_user.identity_type,
        reason=request.reason,
        feedback_comment=request.feedback_comment,
        feedback_rating=request.feedback_rating,
        metadata=request.metadata,
        evidence_reviewed=request.evidence_reviewed,
        evidence_context=request.evidence_context,
        submitted_recommendation_id=request.recommendation_id,
        submitted_decision=request.decision,
        reviewer_roles=sorted(resolve_user_roles(current_user)),
    )
    return result["review"]


@router.post(
    "/recommendations/{recommendation_id}/modify",
    response_model=RecommendationReviewResponse,
)
def modify_recommendation(
    recommendation_id: UUID,
    request: RecommendationReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("CURRICULUM_APPROVER")),
    _academic_permission: User = Depends(require_permission("recommendation.academic_approve")),
):
    result = recommendation_review_service.review(
        db=db,
        recommendation_id=recommendation_id,
        decision="modify",
        reviewer_id=current_user.identity_id,
        reviewer_type=current_user.identity_type,
        reason=request.reason,
        feedback_comment=request.feedback_comment,
        feedback_rating=request.feedback_rating,
        modified_title=request.modified_title,
        modified_description=request.modified_description,
        modified_priority=request.modified_priority,
        metadata=request.metadata,
        evidence_reviewed=request.evidence_reviewed,
        evidence_context=request.evidence_context,
        submitted_recommendation_id=request.recommendation_id,
        submitted_decision=request.decision,
        reviewer_roles=sorted(resolve_user_roles(current_user)),
    )
    return result["review"]


@router.post(
    "/recommendations/{recommendation_id}/feedback",
    response_model=RecommendationFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_recommendation_feedback(
    recommendation_id: UUID,
    request: RecommendationFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recommendation = (
        db.query(Recommendation)
        .filter(Recommendation.recommendation_id == recommendation_id)
        .first()
    )

    if not recommendation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    feedback = RecommendationFeedback(
        recommendation_id=recommendation.recommendation_id,
        reviewer_id=current_user.identity_id,
        feedback_type=request.feedback_type,
        rating=request.rating,
        comment=request.comment,
        feedback_metadata=request.metadata,
    )
    db.add(feedback)

    log_audit_event(
        db=db,
        event_layer="application",
        event_type="recommendation_feedback",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="recommendation.review",
        action="recommendation_feedback_added",
        result="success",
        metadata={
            "recommendation_id": str(recommendation.recommendation_id),
            "feedback_type": request.feedback_type,
        },
    )

    db.commit()
    db.refresh(feedback)
    return feedback


@router.get(
    "/recommendations/{recommendation_id}/reviews",
    response_model=List[RecommendationReviewResponse],
)
def list_recommendation_reviews(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(RecommendationReview)
        .filter(RecommendationReview.recommendation_id == recommendation_id)
        .order_by(RecommendationReview.created_at.asc())
        .all()
    )


@router.get(
    "/recommendations/{recommendation_id}/feedback",
    response_model=List[RecommendationFeedbackResponse],
)
def list_recommendation_feedback(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(RecommendationFeedback)
        .filter(RecommendationFeedback.recommendation_id == recommendation_id)
        .order_by(RecommendationFeedback.created_at.asc())
        .all()
    )


@router.get(
    "/recommendations/{recommendation_id}/status-history",
    response_model=List[RecommendationStatusHistoryResponse],
)
def list_recommendation_status_history(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(RecommendationStatusHistory)
        .filter(RecommendationStatusHistory.recommendation_id == recommendation_id)
        .order_by(RecommendationStatusHistory.created_at.asc())
        .all()
    )

