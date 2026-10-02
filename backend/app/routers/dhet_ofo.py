"""
DHET OFO 2021 acquisition, validation/import, and evidence-mapping API.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dhet_ofo import (
    DHETOFODownloadRequest,
    OFOEvidenceMappingProposeRequest,
    OFOEvidenceMappingReviewRequest,
)
from app.services.dhet_ofo_acquisition_service import (
    DHETOFOAcquisitionError,
    DHETOFOAcquisitionService,
)
from app.services.ofo_mapping_service import OFOMappingError, OFOMappingService

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_enabled():
    if not settings.ENABLE_OFO_TAXONOMY:
        raise HTTPException(status_code=404, detail="OFO taxonomy feature is disabled")


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (DHETOFOAcquisitionError, OFOMappingError)):
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    logger.exception("DHET OFO operation failed")
    return HTTPException(status_code=500, detail="Internal server error")


@router.get("/dhet-ofo/source", response_model=Dict[str, Any])
async def dhet_ofo_source(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Registered DHET OFO 2021 source profile, acquisitions, and import state."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        return service.get_source_summary()
    except Exception as exc:
        raise _error(exc)


@router.get("/dhet-ofo/discovery", response_model=Dict[str, Any])
async def dhet_ofo_discovery(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single best-effort discovery of the official DHET OFO workbook URL."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        return service.discover(operator_id=current_user.identity_id)
    except Exception as exc:
        raise _error(exc)


@router.post("/dhet-ofo/download", response_model=Dict[str, Any])
async def dhet_ofo_download(
    request: DHETOFODownloadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Controlled download from the allowlisted DHET domain (operator-confirmed)."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        return service.download(
            operator_id=current_user.identity_id,
            confirmed=request.confirmed,
            resolved_url=request.resolved_url,
            note=request.note,
        )
    except Exception as exc:
        raise _error(exc)


@router.post("/dhet-ofo/upload", response_model=Dict[str, Any])
async def dhet_ofo_upload(
    file: UploadFile = File(...),
    acquisition_type: str = Query(default="official", pattern="^(official|synthetic_fixture)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manual upload fallback; records the same provenance and checksum as a download."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        content = await file.read()
        return service.upload(
            operator_id=current_user.identity_id,
            content=content,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            acquisition_type=acquisition_type,
        )
    except Exception as exc:
        raise _error(exc)


@router.get("/dhet-ofo/history", response_model=List[Dict[str, Any]])
async def dhet_ofo_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append-only acquisition provenance history."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    summary = service.get_source_summary()
    return summary.get("acquisitions", [])


@router.post("/dhet-ofo/acquisitions/{acquisition_id}/validate", response_model=Dict[str, Any])
async def dhet_ofo_validate(
    acquisition_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate workbook structure before any versioned import."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        return service.validate_acquisition(acquisition_id)
    except Exception as exc:
        raise _error(exc)


@router.post("/dhet-ofo/acquisitions/{acquisition_id}/import", response_model=Dict[str, Any])
async def dhet_ofo_import(
    acquisition_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Versioned, idempotent import of the validated DHET OFO workbook."""
    _check_enabled()
    service = DHETOFOAcquisitionService(db)
    try:
        return service.import_acquisition(acquisition_id, operator_id=current_user.identity_id)
    except Exception as exc:
        raise _error(exc)


@router.get("/dhet-ofo/mappings", response_model=List[Dict[str, Any]])
async def dhet_ofo_list_mappings(
    mapping_status: Optional[str] = Query(default=None, alias="status"),
    search: Optional[str] = Query(default=None, min_length=2),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List OFO evidence mappings (candidate / approved / deferred / ...)."""
    _check_enabled()
    service = OFOMappingService(db)
    rows = service.list_mappings(status=mapping_status, search=search, skip=skip, limit=limit)
    return [_mapping_dict(row, service) for row in rows]


@router.post("/dhet-ofo/mappings", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def dhet_ofo_propose_mapping(
    request: OFOEvidenceMappingProposeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Propose an OFO evidence mapping from full evidence content (never title-only)."""
    _check_enabled()
    service = OFOMappingService(db)
    try:
        mapping = service.propose(request.model_dump(), actor_id=current_user.identity_id)
    except Exception as exc:
        raise _error(exc)
    return _mapping_dict(mapping, service)


@router.post("/dhet-ofo/mappings/{mapping_id}/review", response_model=Dict[str, Any])
async def dhet_ofo_review_mapping(
    mapping_id: UUID,
    request: OFOEvidenceMappingReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append human decision with full audit trail; approvals require real OFO codes."""
    _check_enabled()
    service = OFOMappingService(db)
    try:
        mapping = service.review(
            mapping_id=mapping_id,
            decision=request.decision,
            note=request.note,
            reviewer_id=request.reviewer_id or current_user.identity_id,
            selected_ofo_code=request.selected_ofo_code,
        )
    except Exception as exc:
        raise _error(exc)
    return _mapping_dict(mapping, service)


@router.get("/dhet-ofo/mappings/{mapping_id}/history", response_model=Dict[str, Any])
async def dhet_ofo_mapping_history(
    mapping_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Append-only decision history for one OFO evidence mapping."""
    _check_enabled()
    service = OFOMappingService(db)
    try:
        return service.history(mapping_id)
    except Exception as exc:
        raise _error(exc)


@router.get("/dhet-ofo/stats", response_model=Dict[str, Any])
async def dhet_ofo_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """OFO evidence-mapping status summary plus acquisition overview."""
    _check_enabled()
    mapping_summary = OFOMappingService(db).summary()
    acquisition_summary = DHETOFOAcquisitionService(db).get_source_summary()
    return {
        "mappings": mapping_summary,
        "acquisition": {
            "latest_status": acquisition_summary.get("latest_acquisition", {}).get("status"),
            "import_summary": acquisition_summary.get("import_summary"),
            "occupation_counts_by_version": acquisition_summary.get("occupation_counts_by_version"),
        },
        "enabled": settings.ENABLE_OFO_TAXONOMY,
    }


@router.get("/dhet-ofo/breakdown", response_model=Dict[str, Any])
async def dhet_ofo_breakdown(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auditable OFO reference-table breakdown: code-length buckets and per
    acquisition lineage that reconcile exactly to the displayed portal total."""
    _check_enabled()
    return DHETOFOAcquisitionService(db).get_breakdown()


def _mapping_dict(mapping, service: OFOMappingService) -> Dict[str, Any]:
    metadata = mapping.mapping_metadata or {}
    return {
        "mapping_id": str(mapping.mapping_id),
        "source_record_id": mapping.source_record_id,
        "source_domain": mapping.source_domain,
        "source_entity_type": mapping.source_entity_type,
        "source_entity_id": str(mapping.source_entity_id) if mapping.source_entity_id else None,
        "matched_text": mapping.matched_text,
        "duties_text": mapping.duties_text,
        "education_text": mapping.education_text,
        "experience_text": mapping.experience_text,
        "skills_text": mapping.skills_text,
        "ofo_occupation_id": str(mapping.ofo_occupation_id) if mapping.ofo_occupation_id else None,
        "ofo_code": mapping.ofo_code,
        "occupation_title": mapping.occupation_title,
        "canonical_skill_id": str(mapping.canonical_skill_id) if mapping.canonical_skill_id else None,
        "method": mapping.method,
        "confidence_score": mapping.confidence_score,
        "mapping_status": mapping.mapping_status,
        "reviewer_id": mapping.reviewer_id,
        "reviewed_at": mapping.reviewed_at.isoformat() if mapping.reviewed_at else None,
        "review_note": mapping.review_note,
        "version": mapping.version,
        "title_only": bool(metadata.get("title_only")),
        "defer_reason": metadata.get("defer_reason") or metadata.get("title_only_reason"),
        "review_decision": (metadata.get("review") or {}).get("decision"),
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
    }