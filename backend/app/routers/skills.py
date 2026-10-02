"""
Skills and ESCO harmonisation endpoints.
"""

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.document_chunk import DocumentChunk
from app.models.esco_bundle import ESCOBundle
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.esco_skill import ESCOSkill
from app.models.operational_job import OperationalJob
from app.models.skill_alias import SkillAlias
from app.models.skill_mapping import SkillMapping
from app.models.skill import Skill
from app.models.skill_mapping_review_event import SkillMappingReviewEvent
from app.models.user import User
from app.schemas.skills import (
    AlignmentCalibrationRequest,
    CurriculumSkillExtractionRequest,
    ESCOCrosswalkResponse,
    ESCOImportResponse,
    ESCOOccupationDetailResponse,
    ESCOOccupationImportResponse,
    ESCOOccupationResponse,
    ESCOOccupationSkillLinkResponse,
    ESCOSkillResponse,
    LabourMarketSkillExtractionRequest,
    SemanticSkillMatchRequest,
    SemanticSkillMatchResponse,
    SkillAliasCreateRequest,
    SkillAliasResponse,
    SkillAliasUpdateRequest,
    SkillDemandEvidenceGenerateRequest,
    SkillDemandEvidenceGenerateResponse,
    SkillDemandEvidenceResponse,
    SkillDuplicateCandidateResponse,
    SkillDuplicateMergeRequest,
    SkillExtractionResponse,
    SkillMappingReviewRequest,
    SkillMappingResponse,
    SkillMergeRequest,
    SkillMergeResponse,
    SkillResponse,
    SkillSummaryResponse,
)
from app.services.skill_alignment_validity_service import skill_alignment_validity_service
from app.services.skill_harmonisation_service import skill_harmonisation_service
from app.services.taxonomy_provenance_service import taxonomy_provenance_service
from app.services.esco_bundle_import_service import esco_bundle_import_service
from app.services.operational_job_service import operational_job_service
from app.services.audit_service import log_audit_event
from app.services.structured_log import log_structured

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/skills",
    tags=["skills"],
)


@router.get(
    "/summary",
    response_model=SkillSummaryResponse,
)
def skill_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.summary(db)


@router.get(
    "",
    response_model=List[SkillResponse],
)
def list_skills(
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.list_skills(db, limit=limit)


@router.get("/taxonomy/cleanup-candidates")
def taxonomy_cleanup_candidates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Active inferred entries that have no approved evidence or ESCO link."""
    rows = db.query(Skill).filter(Skill.status == "active", Skill.category == "job_posting").order_by(Skill.name).all()
    items = []
    for skill in rows:
        approved = db.query(func.count(SkillMapping.mapping_id)).filter(
            SkillMapping.skill_id == skill.skill_id,
            SkillMapping.mapping_status == "approved",
        ).scalar() or 0
        total = db.query(func.count(SkillMapping.mapping_id)).filter(SkillMapping.skill_id == skill.skill_id).scalar() or 0
        esco_links = db.query(func.count(ESCOSkill.esco_skill_id)).filter(ESCOSkill.skill_id == skill.skill_id).scalar() or 0
        if approved == 0 and esco_links == 0:
            items.append({"skill_id": str(skill.skill_id), "name": skill.name, "mapping_count": int(total), "approved_mapping_count": 0, "esco_links": 0})
    return {"items": items, "count": len(items)}


@router.post("/taxonomy/archive-unsupported")
def archive_unsupported_taxonomy_entries(
    note: str = Query(min_length=10, max_length=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    preview = taxonomy_cleanup_candidates(db=db, current_user=current_user)
    archived = []
    for item in preview["items"]:
        skill = db.query(Skill).filter(Skill.skill_id == UUID(item["skill_id"]), Skill.status == "active").first()
        if not skill:
            continue
        skill.status = "inactive"
        metadata = dict(skill.skill_metadata or {})
        metadata["taxonomy_cleanup"] = {"reason": note, "actor": current_user.identity_id}
        skill.skill_metadata = metadata
        archived.append(item)
    db.commit()
    log_audit_event(
        db=db,
        event_layer="data_operations",
        event_type="canonical_taxonomy_archive_unsupported",
        actor_type="human",
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="skills_router",
        action="archive_unsupported_canonical_entries",
        result="success",
        metadata={"note": note, "archived": archived},
    )
    return {"archived": archived, "count": len(archived), "note": note}


@router.get(
    "/esco",
    response_model=List[ESCOSkillResponse],
)
def list_esco_skills(
    taxonomy_version: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ESCOSkill)
    if taxonomy_version:
        query = query.filter(ESCOSkill.taxonomy_version == taxonomy_version)
    return query.order_by(ESCOSkill.preferred_label.asc()).limit(limit).all()


@router.post(
    "/esco/import",
    response_model=ESCOImportResponse,
)
async def import_esco_taxonomy(
    file: UploadFile = File(...),
    taxonomy_version: str = "imported",
    dry_run: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = await file.read()
    try:
        records = parse_esco_upload(content, file.filename or "")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if dry_run:
        return skill_alignment_validity_service.esco_import_preview(
            records=records,
            taxonomy_version=taxonomy_version,
        )
    return skill_harmonisation_service.import_esco_records(
        db=db,
        records=records,
        taxonomy_version=taxonomy_version,
        actor_id=current_user.identity_id,
    )


@router.post(
    "/esco/bundle/preview",
)
async def preview_esco_bundle(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Read-only preview of the operator-supplied ESCO distribution (no writes)."""
    payload = []
    for upload in files:
        payload.append({"filename": upload.filename or "unknown.csv", "content": await upload.read()})
    return esco_bundle_import_service.preview_files(payload)


@router.post(
    "/esco/bundle/validate",
)
async def validate_stage_esco_bundle(
    files: List[UploadFile] = File(...),
    note: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Validate checksums/schema and stage the ESCO distribution for a durable import."""
    payload = [
        {"filename": upload.filename or "unknown.csv", "content": await upload.read()}
        for upload in files
    ]
    try:
        return esco_bundle_import_service.validate_and_stage(
            db=db,
            actor_id=current_user.identity_id,
            files=payload,
            note=note,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get(
    "/esco/bundle/runs",
)
def list_esco_bundles(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Append-only ESCO bundle acquisition/import history."""
    return esco_bundle_import_service.list_bundles(db, limit=limit)


@router.get(
    "/esco/bundle/{bundle_id}",
)
def esco_bundle_status(
    bundle_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    try:
        return esco_bundle_import_service.bundle_dict(db, bundle_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/esco/bundle/{bundle_id}/status",
)
def esco_bundle_live_status(
    bundle_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Live bundle status: source/version/licence, import record, checksum and
    reference-table coverage computed from the database at request time."""
    try:
        return esco_bundle_import_service.live_status(db, bundle_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/esco/bundle/{bundle_id}/import",
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_esco_bundle_import(
    bundle_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Enqueue the durable, deterministic ESCO bundle import as an operational job."""
    bundle = db.query(ESCOBundle).filter(ESCOBundle.bundle_id == bundle_id).first()
    if not bundle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bundle not found")
    if bundle.status == "imported":
        return {
            "accepted": False,
            "detail": "Bundle already imported",
            "bundle": esco_bundle_import_service.to_dict(bundle),
        }
    if bundle.status not in {"validated", "partial"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bundle is not importable (status: {bundle.status})",
        )
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="taxonomy.esco.bundle.import",
        requested_by=current_user.identity_id,
        parameters={"bundle_id": str(bundle_id)},
        max_attempts=1,
    )
    return {
        "accepted": created,
        "coalesced": not created,
        "operational_job": operational_job_service.to_dict(job),
        "bundle": esco_bundle_import_service.to_dict(bundle),
    }


@router.post(
    "/esco/seed-expanded",
    response_model=ESCOImportResponse,
)
def seed_expanded_esco(
    taxonomy_version: str = "expanded",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Seed the expanded ESCO taxonomy (~100 skills across all domains)."""
    from app.data.esco_expanded_seed import ESCO_EXPANDED_SEED
    return skill_harmonisation_service.import_esco_records(
        db=db,
        records=ESCO_EXPANDED_SEED,
        taxonomy_version=taxonomy_version,
        actor_id=current_user.identity_id,
    )


@router.get(
    "/esco/crosswalk",
    response_model=ESCOCrosswalkResponse,
)
def esco_crosswalk(
    version_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Build a curriculum-ESCO crosswalk showing which skills map to ESCO."""
    return skill_harmonisation_service.esco_crosswalk(db, version_id=version_id)


@router.get(
    "/occupations",
    response_model=List[ESCOOccupationResponse],
)
def list_esco_occupations(
    taxonomy_version: Optional[str] = None,
    top_concept_only: bool = False,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ESCOOccupation)
    if taxonomy_version:
        query = query.filter(ESCOOccupation.taxonomy_version == taxonomy_version)
    if top_concept_only:
        query = query.filter(ESCOOccupation.top_concept.is_(True))
    return query.order_by(ESCOOccupation.preferred_label.asc()).limit(limit).all()


@router.get(
    "/occupations/isco-bridge",
)
def esco_isco_bridge(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Show the ISCO-08 bridge: which ISCO codes map to which ESCO occupations."""
    from collections import Counter

    occupations = db.query(ESCOOccupation).all()
    isco_to_occupations: dict = {}
    all_isco_codes: list = []

    for occ in occupations:
        isco_codes = occ.occupation_metadata.get("isco_codes", [])
        all_isco_codes.extend(isco_codes)
        for code in isco_codes:
            isco_to_occupations.setdefault(code, []).append(occ.preferred_label)

    isco_counts = Counter(all_isco_codes)

    return {
        "total_occupations": len(occupations),
        "unique_isco_codes": len(isco_counts),
        "isco_coverage": [
            {"isco_code": code, "occupation_count": count, "sample_occupations": isco_to_occupations[code][:5]}
            for code, count in isco_counts.most_common()
        ],
        "isco_hierarchy": {
            "major_groups": [c for c in isco_counts if len(c) == 1],
            "sub_major_groups": [c for c in isco_counts if len(c) == 2],
            "minor_groups": [c for c in isco_counts if len(c) == 3],
            "unit_groups": [c for c in isco_counts if len(c) == 4],
        },
    }


@router.get(
    "/occupations/{occupation_id}",
    response_model=ESCOOccupationDetailResponse,
)
def get_esco_occupation(
    occupation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    occ = db.query(ESCOOccupation).filter(
        ESCOOccupation.esco_occupation_id == occupation_id
    ).first()
    if not occ:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Occupation not found")
    return occ


@router.get(
    "/occupations/search/proxy",
)
def search_esco_occupations_proxy(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """Proxy search to the live ESCO API for occupations."""
    import httpx
    try:
        resp = httpx.get(
            "https://ec.europa.eu/esco/api/search",
            params={"q": q, "type": "occupation", "language": "en", "limit": limit},
            headers={"Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for r in data.get("_embedded", {}).get("results", []):
            results.append({
                "uri": r.get("uri"),
                "title": r.get("title"),
                "code": r.get("code"),
                "broaderOccupation": r.get("broaderOccupation", []),
            })
        return {
            "total": data.get("total", 0),
            "results": results,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ESCO API error: {exc}",
        ) from exc


@router.post(
    "/occupations/import",
    response_model=ESCOOccupationImportResponse,
)
def import_esco_occupations(
    taxonomy_version: str = "occupation_v1",
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import ESCO occupations from the ESCO API (by broad search terms)."""
    return skill_harmonisation_service.import_esco_occupations(
        db=db,
        taxonomy_version=taxonomy_version,
        limit=limit,
    )


@router.get(
    "/occupations/{occupation_id}/skills",
    response_model=List[ESCOOccupationSkillLinkResponse],
)
def get_occupation_skills(
    occupation_id: UUID,
    relationship_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ESCOOccupationSkillLink).filter(
        ESCOOccupationSkillLink.occupation_id == occupation_id
    )
    if relationship_type:
        query = query.filter(ESCOOccupationSkillLink.relationship_type == relationship_type)
    return query.all()


@router.get("/readiness")
def skill_alignment_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return skill_alignment_validity_service.readiness(db)


@router.get("/semantic-candidates/{skill_id}")
def semantic_candidates(
    skill_id: UUID,
    threshold: float = Query(default=0.35, ge=0.0, le=1.0),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        return skill_alignment_validity_service.semantic_candidates_for_skill(
            db=db,
            skill_id=skill_id,
            threshold=threshold,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/alignment-calibration")
def alignment_calibration_summary(
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return skill_alignment_validity_service.alignment_calibration_summary(db=db, limit=limit)


@router.post("/alignment-calibration/{alignment_id}")
def record_alignment_calibration(
    alignment_id: UUID,
    request: AlignmentCalibrationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        row = skill_alignment_validity_service.record_alignment_calibration(
            db=db,
            alignment_id=alignment_id,
            expert_alignment_score=request.expert_alignment_score,
            reviewer_id=current_user.identity_id,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {
        "alignment_id": str(row.alignment_id),
        "status": row.status,
        "alignment_score": row.alignment_score,
        "score_metadata": row.score_metadata,
    }


@router.get(
    "/aliases",
    response_model=List[SkillAliasResponse],
)
def list_skill_aliases(
    skill_id: Optional[UUID] = None,
    active_only: bool = False,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.list_aliases(
        db=db,
        skill_id=skill_id,
        active_only=active_only,
        limit=limit,
    )


@router.post(
    "/aliases",
    response_model=SkillAliasResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_alias(
    request: SkillAliasCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.create_alias(
            db=db,
            skill_id=request.skill_id,
            alias=request.alias,
            language=request.language,
            source=request.source,
            confidence_weight=request.confidence_weight,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/aliases/{alias_id}",
    response_model=SkillAliasResponse,
)
def update_skill_alias(
    alias_id: UUID,
    request: SkillAliasUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.update_alias(
            db=db,
            alias_id=alias_id,
            updates=request.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/semantic-match",
    response_model=List[SemanticSkillMatchResponse],
)
def semantic_skill_match(
    request: SemanticSkillMatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    matches = skill_harmonisation_service.semantic_match_text(
        db=db,
        source_text=request.text,
        threshold=request.threshold,
        limit=request.limit,
    )
    return [
        {
            "skill_id": item["skill"].skill_id,
            "skill_key": item["skill"].skill_key,
            "name": item["skill"].name,
            "confidence_score": item["confidence_score"],
            "semantic_similarity": item.get("semantic_similarity") or 0,
            "confidence_calibration": item.get("calibration") or {},
            "matched_text": item["matched_text"],
        }
        for item in matches
    ]


@router.get("/curriculum/context-preview")
def preview_curriculum_skill_contexts(
    version_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    max_samples: int = Query(default=20, ge=1, le=100),
    include_matches: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    query = db.query(DocumentChunk)
    if version_id:
        query = query.filter(DocumentChunk.version_id == version_id)
    chunks = (
        query
        .order_by(DocumentChunk.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(limit)
        .all()
    )

    alias_index = {}
    esco_by_skill = {}
    if include_matches:
        alias_pairs = skill_harmonisation_service.active_alias_skill_pairs(db)
        alias_index = skill_harmonisation_service.alias_candidate_index(alias_pairs)
        esco_by_skill = skill_harmonisation_service.esco_by_skill_id(db)

    samples = []
    contexts_found = 0
    chunks_with_contexts = 0
    for chunk in chunks:
        metadata = chunk.chunk_metadata or {}
        contexts = skill_harmonisation_service.curriculum_skill_contexts(chunk)
        if contexts:
            chunks_with_contexts += 1
        contexts_found += len(contexts)
        for context in contexts:
            if len(samples) >= max_samples:
                continue
            matches = []
            if include_matches:
                for match in skill_harmonisation_service.extract_alias_matches_from_index(
                    context["text"],
                    alias_index=alias_index,
                    esco_by_skill=esco_by_skill,
                ):
                    if skill_harmonisation_service.is_generic_curriculum_skill(
                        match["matched_text"],
                        match["skill"].name,
                    ):
                        continue
                    matches.append(
                        {
                            "skill_id": str(match["skill"].skill_id),
                            "skill_key": match["skill"].skill_key,
                            "skill_name": match["skill"].name,
                            "matched_text": match["matched_text"],
                            "confidence_score": match["confidence_score"],
                        }
                    )
            samples.append(
                {
                    "chunk_id": str(chunk.chunk_id),
                    "version_id": str(chunk.version_id),
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "source_filename": metadata.get("source_filename"),
                    "document_key": metadata.get("document_key"),
                    "section": metadata.get("section"),
                    "outcome_type": metadata.get("outcome_type"),
                    "evidence_type": metadata.get("curriculum_evidence_type")
                    or skill_harmonisation_service.infer_curriculum_evidence_type(metadata),
                    "context_type": context["context_type"],
                    "quality_weight": context["quality_weight"],
                    "text": context["text"],
                    "candidate_matches": matches[:10],
                }
            )
    return {
        "chunks_scanned": len(chunks),
        "chunks_with_contexts": chunks_with_contexts,
        "contexts_found": contexts_found,
        "samples_returned": len(samples),
        "samples": samples,
    }

@router.post(
    "/extract/curriculum",
    response_model=SkillExtractionResponse,
)
def extract_curriculum_skills(
    request: CurriculumSkillExtractionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.extract_from_curriculum(
        db=db,
        version_id=request.version_id,
        limit=request.limit,
    )


@router.post(
    "/extract/labour-market",
    response_model=SkillExtractionResponse,
)
def extract_labour_market_skills(
    request: LabourMarketSkillExtractionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.extract_from_labour_market(
        db=db,
        limit=request.limit,
    )


@router.post(
    "/demand-evidence/generate",
    response_model=SkillDemandEvidenceGenerateResponse,
)
def generate_skill_demand_evidence(
    request: SkillDemandEvidenceGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.generate_skill_demand_evidence(
        db=db,
        limit=request.limit,
    )


@router.get(
    "/demand-evidence",
    response_model=List[SkillDemandEvidenceResponse],
)
def list_skill_demand_evidence(
    skill_id: Optional[UUID] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.list_skill_demand_evidence(
        db=db,
        skill_id=skill_id,
        limit=limit,
    )


@router.get(
    "/mappings",
    response_model=List[SkillMappingResponse],
)
def list_skill_mappings(
    source_domain: Optional[str] = None,
    mapping_status: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SkillMapping)

    if source_domain:
        query = query.filter(SkillMapping.source_domain == source_domain)
    if mapping_status:
        query = query.filter(SkillMapping.mapping_status == mapping_status)

    return (
        query
        .order_by(SkillMapping.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


@router.get(
    "/governance/summary",
)
def skill_governance_summary(
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    summary = skill_harmonisation_service.summary(db)
    candidate_mappings = (
        db.query(SkillMapping)
        .filter(SkillMapping.mapping_status == "candidate")
        .order_by(SkillMapping.confidence_score.asc(), SkillMapping.created_at.desc())
        .limit(limit)
        .all()
    )
    needs_review_mappings = (
        db.query(SkillMapping)
        .filter(SkillMapping.mapping_status == "needs_review")
        .order_by(SkillMapping.confidence_score.asc(), SkillMapping.created_at.desc())
        .limit(limit)
        .all()
    )
    duplicate_candidates = skill_harmonisation_service.duplicate_candidates(
        db=db,
        limit=limit,
        min_score=0.86,
    )
    return {
        "summary": summary,
        "candidate_mapping_count": summary.get("candidate_mappings", 0),
        "approved_mapping_count": summary.get("approved_mappings", 0),
        "rejected_mapping_count": summary.get("rejected_mappings", 0),
        "duplicate_candidate_count": len(duplicate_candidates),
        "candidate_mappings": candidate_mappings,
        "needs_review_mappings": needs_review_mappings,
        "duplicate_candidates": duplicate_candidates,
        "next_actions": [
            "Approve high-confidence candidate mappings.",
            "Reject noisy or generic mappings.",
            "Merge duplicate skill candidates.",
            "Re-run processing summary after governance actions.",
        ],
    }


@router.get(
    "/taxonomy/provenance",
)
def taxonomy_provenance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Taxonomy source, coverage, and explainability provenance for ESCO/OFO."""
    return taxonomy_provenance_service.build(db)


@router.get(
    "/mappings/{mapping_id}/history",
)
def mapping_review_history(
    mapping_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    """Append-only decision history for one skill mapping (audit trail)."""
    mapping = db.query(SkillMapping).filter(SkillMapping.mapping_id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    events = (
        db.query(SkillMappingReviewEvent)
        .filter(SkillMappingReviewEvent.mapping_id == mapping_id)
        .order_by(SkillMappingReviewEvent.created_at.asc())
        .all()
    )
    return {
        "mapping_id": str(mapping.mapping_id),
        "mapping_status": mapping.mapping_status,
        "matched_text": mapping.matched_text,
        "history": [
            {
                "review_event_id": str(event.review_event_id),
                "previous_status": event.previous_status,
                "decision": event.decision,
                "previous_skill_id": str(event.previous_skill_id),
                "selected_skill_id": str(event.selected_skill_id),
                "reviewer_id": event.reviewer_id,
                "note": event.note,
                "timestamp": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        "audit_ids": [
            str(event.review_event_id)
            for event in events
        ],
    }


@router.get("/governance/workbench")
def skill_mapping_governance_workbench(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    review_status: Optional[str] = Query(default=None, pattern="^(candidate|needs_review|approved|rejected|deferred)$"),
    mapping_id: Optional[UUID] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    readiness = skill_alignment_validity_service.readiness(db)
    queue_query = (
        db.query(SkillMapping, Skill.name, ESCOSkill.preferred_label)
        .join(Skill, Skill.skill_id == SkillMapping.skill_id)
        .outerjoin(ESCOSkill, ESCOSkill.esco_skill_id == SkillMapping.esco_skill_id)
    )
    if mapping_id:
        queue_query = queue_query.filter(SkillMapping.mapping_id == mapping_id)
    else:
        queue_query = queue_query.filter(SkillMapping.mapping_status.in_(["candidate", "needs_review"]))
    if review_status and not mapping_id:
        queue_query = queue_query.filter(SkillMapping.mapping_status == review_status)
    queue_total = queue_query.count()
    rows = queue_query.order_by(
        SkillMapping.confidence_score.asc(), SkillMapping.created_at.asc(), SkillMapping.mapping_id.asc()
    ).offset(offset).limit(limit).all()
    status_rows = (
        db.query(SkillMapping.mapping_status, func.count(SkillMapping.mapping_id))
        .group_by(SkillMapping.mapping_status)
        .all()
    )
    status_counts = {status: int(count or 0) for status, count in status_rows}
    auto_approved_count = (
        db.query(func.count(SkillMapping.mapping_id))
        .filter(
            SkillMapping.mapping_status == "approved",
            SkillMapping.mapping_metadata.has_key("auto_review"),  # noqa: W601 - SQLAlchemy JSONB operator
        )
        .scalar()
        or 0
    )
    candidate_bands = db.query(
        func.count(SkillMapping.mapping_id).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score >= 0.90,
        ).label("high_90"),
        func.count(SkillMapping.mapping_id).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score >= 0.85,
            SkillMapping.confidence_score < 0.90,
        ).label("band_85_90"),
        func.count(SkillMapping.mapping_id).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score >= 0.70,
            SkillMapping.confidence_score < 0.85,
        ).label("band_70_85"),
        func.count(SkillMapping.mapping_id).filter(
            SkillMapping.mapping_status == "candidate",
            SkillMapping.confidence_score < 0.70,
        ).label("below_70"),
    ).one()
    latest_job = (
        db.query(OperationalJob)
        .filter(OperationalJob.job_type == "skills.extract.evidence")
        .order_by(OperationalJob.created_at.desc())
        .first()
    )
    latest_job_payload = None
    if latest_job:
        latest_job_payload = {
            "job_id": str(latest_job.job_id),
            "status": latest_job.status,
            "progress_current": latest_job.progress_current,
            "progress_total": latest_job.progress_total,
            "progress_message": latest_job.progress_message,
            "created_at": latest_job.created_at.isoformat() if latest_job.created_at else None,
            "started_at": latest_job.started_at.isoformat() if latest_job.started_at else None,
            "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            "result": latest_job.result or {},
            "error_summary": latest_job.error_summary,
        }
    queue = []
    for mapping, skill_name, esco_label in rows:
        mapping_metadata = mapping.mapping_metadata or {}
        queue.append(
            {
                "mapping_id": str(mapping.mapping_id),
                "skill_id": str(mapping.skill_id),
                "skill_name": skill_name,
                "esco_label": esco_label,
                "source_domain": mapping.source_domain,
                "source_label": mapping_metadata.get("source"),
                "job_title": mapping_metadata.get("job_title"),
                "posting_id": mapping_metadata.get("posting_id"),
                "job_id": mapping_metadata.get("job_id"),
                "matched_text": mapping.matched_text,
                "evidence_text": mapping.evidence_text,
                "confidence_score": mapping.confidence_score,
                "mapping_status": mapping.mapping_status,
                "extraction_method": mapping.extraction_method,
                "reviewed_by": mapping.reviewed_by,
            }
        )
    return {
        "readiness": readiness,
        "review_queue": queue,
        "review_queue_count": len(queue),
        "review_queue_total": queue_total,
        "review_queue_offset": offset,
        "review_queue_status": review_status,
        "mapping_status_summary": {
            "approved": status_counts.get("approved", 0),
            "auto_approved": int(auto_approved_count),
            "candidate": status_counts.get("candidate", 0),
            "needs_review": status_counts.get("needs_review", 0),
            "rejected": status_counts.get("rejected", 0),
            "candidate_confidence_bands": {
                "high_90": int(candidate_bands.high_90 or 0),
                "band_85_90": int(candidate_bands.band_85_90 or 0),
                "band_70_85": int(candidate_bands.band_70_85 or 0),
                "below_70": int(candidate_bands.below_70 or 0),
            },
            "auto_approval_threshold": 0.90,
            "latest_generation_job": latest_job_payload,
            "deferred": status_counts.get("deferred", 0),
        },
        "review_history_count": db.query(func.count(SkillMappingReviewEvent.review_event_id)).scalar() or 0,
    }


@router.post("/extract/evidence-job", status_code=status.HTTP_202_ACCEPTED)
def enqueue_skill_evidence_extraction(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    job, created = operational_job_service.enqueue(
        db=db,
        job_type="skills.extract.evidence",
        requested_by=current_user.identity_id,
        parameters={"curriculum_limit": 1000, "labour_market_limit": 100},
        max_attempts=1,
    )
    return {
        "accepted": created,
        "coalesced": not created,
        "operational_job": operational_job_service.to_dict(job),
    }

@router.get(
    "/duplicates/candidates",
    response_model=List[SkillDuplicateCandidateResponse],
)
def duplicate_skill_candidates(
    limit: int = Query(default=100, ge=1, le=1000),
    min_score: float = Query(default=0.86, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.duplicate_candidates(
        db=db,
        limit=limit,
        min_score=min_score,
    )


@router.post(
    "/duplicates/merge",
    response_model=SkillMergeResponse,
)
def merge_duplicate_skill_candidate(
    request: SkillDuplicateMergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.merge_duplicate_candidate(
            db=db,
            source_skill_id=request.source_skill_id,
            target_skill_id=request.target_skill_id,
            actor_id=current_user.identity_id,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/mappings/bulk-review",
)
def bulk_review_skill_mappings(
    decision: str = Query(default="approved", pattern="^(approved|rejected|needs_review)$"),
    source_domain: Optional[str] = None,
    min_confidence: float = Query(default=0.85, ge=0.0, le=1.0),
    limit: int = Query(default=100, ge=1, le=5000),
    max_evidence_chars: int = Query(default=120, ge=20, le=1000),
    dry_run: bool = True,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(SkillMapping).filter(
        SkillMapping.mapping_status == "candidate",
        SkillMapping.confidence_score >= min_confidence,
    )
    if source_domain:
        query = query.filter(SkillMapping.source_domain == source_domain)
    candidates = query.order_by(SkillMapping.confidence_score.desc(), SkillMapping.created_at.asc()).limit(limit * 20).all()
    mappings = []
    excluded_noisy = 0
    for candidate in candidates:
        evidence_text = candidate.evidence_text or candidate.matched_text or ""
        if len(evidence_text) > max_evidence_chars or "\n" in evidence_text:
            excluded_noisy += 1
            continue
        mappings.append(candidate)
        if len(mappings) >= limit:
            break
    if dry_run:
        return {
            "dry_run": True,
            "decision": decision,
            "matched": len(mappings),
            "excluded_noisy": excluded_noisy,
            "max_evidence_chars": max_evidence_chars,
            "min_confidence": min_confidence,
            "source_domain": source_domain,
            "sample": mappings[:25],
        }
    for mapping in mappings:
        mapping.mapping_status = decision
        mapping.reviewed_by = current_user.identity_id
        mapping.reviewed_at = datetime.now(timezone.utc)
        mapping.review_note = note or f"Bulk {decision} at confidence >= {min_confidence}"
        mapping.mapping_metadata = {
            **(mapping.mapping_metadata or {}),
            "bulk_review": {
                "decision": decision,
                "reviewed_by": current_user.identity_id,
                "min_confidence": min_confidence,
                "source_domain": source_domain,
                "max_evidence_chars": max_evidence_chars,
                "note": note,
            },
        }
        db.add(mapping)
    db.commit()
    log_structured(
        logger,
        "mapping_bulk_review",
        action="bulk_review_applied",
        decision=decision,
        updated=len(mappings),
        excluded_noisy=excluded_noisy,
        source_domain=source_domain,
        min_confidence=min_confidence,
        reviewer_id=current_user.identity_id,
    )
    return {
        "dry_run": False,
        "decision": decision,
        "updated": len(mappings),
        "excluded_noisy": excluded_noisy,
        "max_evidence_chars": max_evidence_chars,
        "min_confidence": min_confidence,
        "source_domain": source_domain,
    }

@router.get(
    "/quality/noisy-job-skills",
)
def noisy_job_skill_queue(
    limit: int = Query(default=100, ge=1, le=1000),
    include_reviewed: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "items": skill_harmonisation_service.noisy_job_skill_queue(
            db=db,
            limit=limit,
            include_reviewed=include_reviewed,
        ),
        "limit": limit,
        "include_reviewed": include_reviewed,
    }


@router.post(
    "/quality/noisy-job-skills/review",
)
def review_noisy_job_skills(
    decision: str = Query(default="needs_review", pattern="^(needs_review|rejected)$"),
    limit: int = Query(default=100, ge=1, le=1000),
    dry_run: bool = True,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.review_noisy_job_skills(
            db=db,
            reviewer_id=current_user.identity_id,
            decision=decision,
            limit=limit,
            dry_run=dry_run,
            note=note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/quality/aliases",
)
def alias_quality_queue(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "items": skill_harmonisation_service.alias_quality_queue(db=db, limit=limit),
        "limit": limit,
    }


@router.post(
    "/quality/aliases/review",
)
def review_alias_quality(
    limit: int = Query(default=100, ge=1, le=1000),
    dry_run: bool = True,
    deactivate: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.review_alias_quality(
        db=db,
        limit=limit,
        dry_run=dry_run,
        deactivate=deactivate,
    )


@router.get(
    "/quality/low-confidence-mappings",
    response_model=List[SkillMappingResponse],
)
def low_confidence_mapping_queue(
    threshold: float = Query(default=0.50, ge=0.0, le=1.0),
    source_domain: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.low_confidence_mapping_queue(
        db=db,
        threshold=threshold,
        source_domain=source_domain,
        limit=limit,
    )


@router.post(
    "/quality/low-confidence-mappings/review",
)
def review_low_confidence_mappings(
    threshold: float = Query(default=0.50, ge=0.0, le=1.0),
    source_domain: Optional[str] = None,
    decision: str = Query(default="needs_review", pattern="^(needs_review|rejected)$"),
    limit: int = Query(default=100, ge=1, le=5000),
    dry_run: bool = True,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.review_low_confidence_mappings(
            db=db,
            reviewer_id=current_user.identity_id,
            threshold=threshold,
            source_domain=source_domain,
            decision=decision,
            limit=limit,
            dry_run=dry_run,
            note=note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/quality/duplicates/review",
)
def duplicate_quality_review(
    limit: int = Query(default=50, ge=1, le=500),
    min_score: float = Query(default=0.97, ge=0.0, le=1.0),
    dry_run: bool = True,
    auto_merge: bool = False,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return skill_harmonisation_service.duplicate_quality_review(
        db=db,
        actor_id=current_user.identity_id,
        limit=limit,
        min_score=min_score,
        dry_run=dry_run,
        auto_merge=auto_merge,
        note=note,
    )
@router.post(
    "/mappings/{mapping_id}/review",
    response_model=SkillMappingResponse,
)
def review_skill_mapping(
    mapping_id: UUID,
    request: SkillMappingReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    try:
        return skill_harmonisation_service.review_mapping(
            db=db,
            mapping_id=mapping_id,
            decision=request.decision,
            reviewer_id=current_user.identity_id,
            note=request.note,
            skill_id=request.skill_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/merge",
    response_model=SkillMergeResponse,
)
def merge_skills(
    request: SkillMergeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return skill_harmonisation_service.merge_skills(
            db=db,
            source_skill_id=request.source_skill_id,
            target_skill_id=request.target_skill_id,
            actor_id=current_user.identity_id,
            note=request.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def parse_esco_upload(content: bytes, filename: str) -> List[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    lowered = filename.lower()
    if lowered.endswith(".json"):
        payload = json.loads(text)
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("skills", "records", "data", "results"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        raise ValueError("JSON ESCO import must be a list or contain skills/records/data/results.")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV ESCO import has no header row.")
    return [dict(row) for row in reader]

