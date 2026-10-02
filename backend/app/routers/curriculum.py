"""
Curriculum document ingestion endpoints.
"""

from __future__ import annotations

import difflib
import ipaddress
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
import requests
import urllib3
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, require_role
from app.core.tenant_scope import assert_entity_access, scope_query
from app.db.session import get_db
from app.models.academic_department import AcademicDepartment
from app.models.academic_faculty import AcademicFaculty
from app.models.academic_programme import AcademicProgramme
from app.models.curriculum_document import CurriculumDocument
from app.models.curriculum_document_version import CurriculumDocumentVersion
from app.models.curriculum_module import CurriculumModule
from app.models.curriculum_evidence_review import CurriculumEvidenceReview
from app.models.curriculum_governance_evidence import CurriculumGovernanceEvidence
from app.models.curriculum_subject_profile import CurriculumSubjectProfile
from app.models.document_chunk import DocumentChunk
from app.models.skill_mapping import SkillMapping
from app.models.user import User
from app.schemas.curriculum_document import (
    CPUTProspectusImportRequest,
    CPUTProspectusImportResponse,
    CurriculumDocumentDetailResponse,
    CurriculumApiImportRequest,
    CurriculumDiscoveryRequest,
    CurriculumDiscoveryResponse,
    CurriculumDocumentResponse,
    CurriculumHierarchyResponse,
    CurriculumModuleResponse,
    CurriculumDocumentVersionResponse,
    CurriculumVersionComparisonResponse,
    CurriculumUploadResponse,
    CurriculumEvidenceReviewRequest,
    CurriculumGovernanceEvidenceCreate,
    DocumentChunkResponse,
)
from app.services.ingestion.curriculum_pdf_service import (
    CURRICULUM_EVIDENCE_TYPES,
    curriculum_pdf_ingestion_service,
)
from app.services.ingestion.curriculum_durable_service import stage_curriculum_upload
from app.services.operational_job_service import operational_job_service
from app.services.ingestion.cput_prospectus_connector import (
    cput_prospectus_connector,
)
from app.services.curriculum_quality_service import curriculum_quality_service
from app.services.curriculum_subject_profile_service import curriculum_subject_profile_service
from app.services.audit_service import log_audit_event

logger = logging.getLogger(__name__)




class SubjectProfileUpdateRequest(BaseModel):
    institution: Optional[str] = None
    faculty: Optional[str] = None
    department: Optional[str] = None
    programme_name: Optional[str] = None
    programme_code: Optional[str] = None
    qualification_type: Optional[str] = None
    subject_code: Optional[str] = Field(default=None, max_length=50)
    subject_name: Optional[str] = None
    subject_year: Optional[int] = None
    nqf_level: Optional[int] = None
    credits: Optional[int] = None
    purpose: Optional[str] = None
    articulation: Optional[str] = None
    validation_status: str = "validated"
    validation_notes: Optional[str] = None

router = APIRouter(
    prefix="/curriculum",
    tags=["curriculum"],
)

GOVERNANCE_LAYER_ORDER = [
    "legislation", "nqf", "heqsf", "che_standard", "che_accreditation",
    "dhet_pqm", "saqa_registration", "institutional_programme", "module_curriculum",
]


def _subject_profile_dict(profile: CurriculumSubjectProfile) -> Dict:
    return {
        "profile_id": str(profile.profile_id), "document_id": str(profile.document_id), "version_id": str(profile.version_id),
        "institution": profile.institution, "faculty": profile.faculty, "department": profile.department,
        "programme_name": profile.programme_name, "programme_code": profile.programme_code, "qualification_type": profile.qualification_type,
        "subject_code": profile.subject_code, "subject_name": profile.subject_name, "subject_year": profile.subject_year,
        "nqf_level": profile.nqf_level, "credits": profile.credits, "status": profile.status, "purpose": profile.purpose,
        "prerequisites": profile.prerequisites or [], "articulation": profile.articulation,
        "learning_outcomes": profile.learning_outcomes or [], "assessment_evidence": profile.assessment_evidence or [],
        "topic_evidence": profile.topic_evidence or [], "extracted_skills": profile.extracted_skills or [],
        "source_version_ids": profile.source_version_ids or [], "source_chunk_ids": profile.source_chunk_ids or [],
        "extraction_metadata": profile.extraction_metadata or {},
        "validation_status": profile.validation_status,
        "validated_by": profile.validated_by,
        "validation_notes": profile.validation_notes,
        "validation_metadata": profile.validation_metadata or {},
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _latest_subject_profiles(profiles):
    """Return the authoritative latest profile for each document and subject.

    Re-uploaded documents retain older version profiles for audit, but those
    historical rows must not keep the consolidated validation queue open.
    """
    latest = {}
    for profile in profiles:
        key = (profile.document_id, profile.subject_code)
        current = latest.get(key)
        candidate_key = (profile.created_at or datetime.min, str(profile.profile_id))
        current_key = (current.created_at or datetime.min, str(current.profile_id)) if current else None
        if current_key is None or candidate_key > current_key:
            latest[key] = profile
    return list(latest.values())


@router.get("/subject-profiles")
def list_curriculum_subject_profiles(subject_code: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = scope_query(db.query(CurriculumSubjectProfile), CurriculumSubjectProfile, current_user, include_shared=True)
    if subject_code:
        query = query.filter(CurriculumSubjectProfile.subject_code == subject_code.upper())
    profiles = query.order_by(CurriculumSubjectProfile.subject_code.asc(), CurriculumSubjectProfile.created_at.desc()).all()
    return {"items": [_subject_profile_dict(profile) for profile in profiles], "total": len(profiles)}




@router.get("/subject-profiles/consolidated")
def list_consolidated_curriculum_subject_profiles(
    subject_code: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = scope_query(db.query(CurriculumSubjectProfile), CurriculumSubjectProfile, current_user, include_shared=True)
    if subject_code:
        query = query.filter(CurriculumSubjectProfile.subject_code == subject_code.upper())
    profiles = query.order_by(CurriculumSubjectProfile.subject_code.asc(), CurriculumSubjectProfile.created_at.asc()).all()
    profiles = _latest_subject_profiles(profiles)
    grouped: Dict[str, Dict] = {}
    for profile in profiles:
        key = profile.subject_code
        item = grouped.setdefault(key, {
            "profile_id": str(profile.profile_id),
            "subject_code": profile.subject_code,
            "subject_name": profile.subject_name,
            "institution": profile.institution,
            "faculty": profile.faculty,
            "department": profile.department,
            "programme_name": profile.programme_name,
            "programme_code": profile.programme_code,
            "qualification_type": profile.qualification_type,
            "subject_year": profile.subject_year,
            "nqf_level": profile.nqf_level,
            "credits": profile.credits,
            "purpose": profile.purpose,
            "prerequisites": [],
            "learning_outcomes": [],
            "assessment_evidence": [],
            "topic_evidence": [],
            "extracted_skills": [],
            "source_profiles": [],
            "source_version_ids": [],
            "validation_statuses": [],
            "validation_status": None,
            "validation_notes": None,
        })
        current_status = profile.validation_status or "needs_review"
        item["profile_id"] = str(profile.profile_id)
        item["validation_statuses"].append(current_status)
        if current_status == "validated" and profile.validation_notes:
            item["validation_notes"] = profile.validation_notes
        for scalar in ["institution", "faculty", "department", "programme_name", "programme_code", "qualification_type", "subject_year", "nqf_level", "credits", "purpose"]:
            current_value = item.get(scalar)
            new_value = getattr(profile, scalar, None)
            # Prefer reviewed/validated profile values over older placeholder values.
            if new_value and (not current_value or current_value in {"Subject guide pilot", "Programme not confirmed", "CPUT"} or current_status == "validated"):
                item[scalar] = new_value
        item["source_profiles"].append({
            "profile_id": str(profile.profile_id),
            "version_id": str(profile.version_id),
            "subject_name": profile.subject_name,
            "validation_status": current_status,
            "source_filename": (profile.extraction_metadata or {}).get("source_filename"),
        })
        item["source_version_ids"].extend([v for v in (profile.source_version_ids or []) if v not in item["source_version_ids"]])
        for field in ["prerequisites", "learning_outcomes", "assessment_evidence", "topic_evidence"]:
            seen = {str(existing) for existing in item[field]}
            for value in (getattr(profile, field) or []):
                marker = str(value)
                if marker not in seen:
                    item[field].append(value)
                    seen.add(marker)
        skill_seen = {str(skill.get("skill_name", "")).lower() for skill in item["extracted_skills"] if isinstance(skill, dict)}
        for skill in (profile.extracted_skills or []):
            name = str(skill.get("skill_name", "")).lower() if isinstance(skill, dict) else str(skill).lower()
            if name and name not in skill_seen:
                item["extracted_skills"].append(skill)
                skill_seen.add(name)
    status_order = {"rejected": 0, "changes_required": 1, "needs_review": 2, "validated": 3}
    items = []
    for item in grouped.values():
        statuses = item.pop("validation_statuses", []) or ["needs_review"]
        if all(status == "validated" for status in statuses):
            item["validation_status"] = "validated"
        elif any(status == "changes_required" for status in statuses):
            item["validation_status"] = "changes_required"
        elif any(status == "rejected" for status in statuses) and not any(status in {"needs_review", "changes_required"} for status in statuses):
            item["validation_status"] = "rejected"
        else:
            item["validation_status"] = min(statuses, key=lambda status: status_order.get(status, 2))
        items.append(item)
    return {"items": items, "total": len(items)}




@router.patch("/subject-profiles/{profile_id}")
def update_curriculum_subject_profile(
    profile_id: UUID,
    payload: SubjectProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST")),
):
    profile = db.query(CurriculumSubjectProfile).filter(CurriculumSubjectProfile.profile_id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject profile not found")
    assert_entity_access(profile, current_user)

    before = _subject_profile_dict(profile)
    editable_fields = [
        "institution", "faculty", "department", "programme_name", "programme_code",
        "qualification_type", "subject_code", "subject_name", "subject_year", "nqf_level",
        "credits", "purpose", "articulation",
    ]
    changes = {}
    data = payload.model_dump(exclude_unset=True)
    for field in editable_fields:
        if field in data:
            old_value = getattr(profile, field)
            new_value = data[field]
            if field == "subject_code" and new_value:
                new_value = str(new_value).upper().strip()
            if old_value != new_value:
                changes[field] = {"old": old_value, "new": new_value}
                setattr(profile, field, new_value)

    allowed_statuses = {"needs_review", "validated", "changes_required", "rejected"}
    if payload.validation_status not in allowed_statuses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid validation status")
    profile.validation_status = payload.validation_status
    profile.validation_notes = payload.validation_notes
    profile.validated_by = current_user.identity_id
    profile.validation_metadata = {
        **(profile.validation_metadata or {}),
        "last_action": "profile_update",
        "changed_fields": sorted(changes.keys()),
    }
    document = db.query(CurriculumDocument).filter(CurriculumDocument.document_id == profile.document_id).first()
    if document:
        document.faculty = profile.faculty
        document.department = profile.department
        document.programme = profile.programme_name
        document.document_metadata = {
            **(document.document_metadata or {}),
            "reporting_metadata_source": "validated_subject_profile",
            "reporting_profile_id": str(profile.profile_id),
        }
        db.add(document)
        if document.programme_id:
            programme = db.query(AcademicProgramme).filter(
                AcademicProgramme.programme_id == document.programme_id
            ).first()
            if programme and profile.programme_name:
                programme.name = profile.programme_name
                programme.qualification_type = profile.qualification_type or programme.qualification_type
                programme.nqf_level = str(profile.nqf_level) if profile.nqf_level else programme.nqf_level
                programme.programme_metadata = {
                    **(programme.programme_metadata or {}),
                    "reporting_metadata_source": "validated_subject_profile",
                    "reporting_profile_id": str(profile.profile_id),
                }
                db.add(programme)

    canonical_module = curriculum_subject_profile_service._upsert_module(
        db,
        document,
        profile.subject_code,
        profile.subject_name,
        profile.nqf_level,
        profile.credits,
        profile.purpose,
    )
    if canonical_module:
        canonical_module.is_active = True
        profile.module_id = canonical_module.module_id
        db.add(profile)
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="curriculum_subject_profile",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="curriculum.api",
        action="update_subject_profile",
        result="success",
        metadata={"profile_id": str(profile.profile_id), "subject_code": profile.subject_code, "changes": changes, "before_status": before.get("validation_status"), "after_status": profile.validation_status},
    )
    db.commit()
    db.refresh(profile)
    return _subject_profile_dict(profile)


@router.post("/versions/{version_id}/subject-profile/rebuild")
def rebuild_curriculum_subject_profile(version_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_role("ADMIN", "ANALYST"))):
    version = db.query(CurriculumDocumentVersion).filter(CurriculumDocumentVersion.version_id == version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
    assert_entity_access(version, current_user)
    profile = curriculum_subject_profile_service.build_for_version(db, version.version_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No chunks are available for this version yet")
    version.extraction_metadata = {**(version.extraction_metadata or {}), "subject_profile_id": str(profile.profile_id), "subject_code": profile.subject_code, "structured_profile_ready": True}
    db.commit()
    db.refresh(profile)
    return _subject_profile_dict(profile)


def _governance_evidence_dict(item: CurriculumGovernanceEvidence) -> Dict:
    return {
        "evidence_id": str(item.evidence_id),
        "parent_evidence_id": str(item.parent_evidence_id) if item.parent_evidence_id else None,
        "tenant_id": str(item.tenant_id) if item.tenant_id else None,
        "programme_id": str(item.programme_id) if item.programme_id else None,
        "document_version_id": str(item.document_version_id) if item.document_version_id else None,
        "layer": item.layer,
        "authority": item.authority,
        "evidence_key": item.evidence_key,
        "title": item.title,
        "identifier": item.identifier,
        "version_label": item.version_label,
        "official_url": item.official_url,
        "effective_from": item.effective_from.isoformat() if item.effective_from else None,
        "effective_to": item.effective_to.isoformat() if item.effective_to else None,
        "currency_status": item.currency_status,
        "verification_status": item.verification_status,
        "nqf_level": item.nqf_level,
        "credits": item.credits,
        "notes": item.notes,
        "evidence_metadata": item.evidence_metadata or {},
        "verified_by": item.verified_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/governance/chain")
def get_curriculum_governance_chain(
    programme_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = scope_query(
        db.query(CurriculumGovernanceEvidence),
        CurriculumGovernanceEvidence,
        current_user,
        include_shared=True,
    ).all()
    items.sort(key=lambda item: (GOVERNANCE_LAYER_ORDER.index(item.layer), item.title))
    required_programme_layers = {
        "che_accreditation", "dhet_pqm", "saqa_registration",
        "institutional_programme", "module_curriculum",
    }
    programme = None
    programme_items = []
    if programme_id:
        programme = db.query(AcademicProgramme).filter(
            AcademicProgramme.programme_id == programme_id
        ).first()
        if not programme:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Programme not found")
        programme_items = [item for item in items if item.programme_id == programme_id]
    verified_programme_items = [
        item for item in programme_items
        if item.verification_status == "verified" and item.currency_status in {"current", "historical"}
    ]
    empirical_programme_layers = {
        item.layer for item in verified_programme_items
        if (item.evidence_metadata or {}).get("evidence_class") != "synthetic_uat"
    }
    technical_programme_layers = {item.layer for item in verified_programme_items}
    return {
        "items": [_governance_evidence_dict(item) for item in items],
        "summary": {
            "total": len(items),
            "verified": sum(item.verification_status == "verified" for item in items),
            "historical": sum(item.currency_status == "historical" for item in items),
            "selected_programme_id": str(programme_id) if programme_id else None,
            "selected_programme_name": programme.name if programme else None,
            "missing_or_unverified_layers": sorted(required_programme_layers - empirical_programme_layers),
            "technical_demo_missing_layers": sorted(required_programme_layers - technical_programme_layers),
            "synthetic_uat_layers": sorted(technical_programme_layers - empirical_programme_layers),
            "programme_evidence_ready": bool(programme_id) and required_programme_layers.issubset(empirical_programme_layers),
            "technical_demo_ready": bool(programme_id) and required_programme_layers.issubset(technical_programme_layers),
        },
        "interpretation": (
            "Shared national references provide context. A programme becomes decision-ready only "
            "when its CHE accreditation, DHET PQM, SAQA registration, institutional curriculum, "
            "and module evidence are linked and verified. Synthetic UAT evidence may prove the "
            "technical workflow but is excluded from empirical programme readiness."
        ),
    }


@router.post("/governance/evidence", status_code=status.HTTP_201_CREATED)
def create_curriculum_governance_evidence(
    payload: CurriculumGovernanceEvidenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST")),
):
    programme_layers = {
        "che_accreditation", "dhet_pqm", "saqa_registration",
        "institutional_programme", "module_curriculum",
    }
    if payload.layer in programme_layers and not payload.programme_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Programme-level governance evidence must be linked to a programme",
        )
    if db.query(CurriculumGovernanceEvidence).filter(
        CurriculumGovernanceEvidence.evidence_key == payload.evidence_key
    ).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Evidence key already exists")
    if payload.programme_id:
        programme = db.query(AcademicProgramme).filter(
            AcademicProgramme.programme_id == payload.programme_id
        ).first()
        if not programme:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Programme not found")
    if payload.document_version_id:
        version = db.query(CurriculumDocumentVersion).filter(
            CurriculumDocumentVersion.version_id == payload.document_version_id
        ).first()
        if not version:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document version not found")
        assert_entity_access(version, current_user)
    item = CurriculumGovernanceEvidence(
        **payload.model_dump(),
        tenant_id=current_user.tenant_id,
        verified_by=current_user.identity_id if payload.verification_status == "verified" else None,
    )
    db.add(item)
    db.flush()
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="curriculum_governance_evidence",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="curriculum.api",
        action="create_governance_evidence",
        result="success",
        metadata={"evidence_id": str(item.evidence_id), "layer": item.layer, "status": item.verification_status},
    )
    db.commit()
    db.refresh(item)
    return _governance_evidence_dict(item)


def sanitised_endpoint_url(url: str) -> str:
    """Remove credentials, query values, and fragments before durable metadata."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return parsed._replace(
        netloc=netloc,
        query="",
        fragment="",
    ).geturl()


def _validate_url_not_internal(url: str) -> None:
    """Raise HTTPException if URL resolves to a private/internal IP."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid URL: no hostname",
        )
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        hostname = hostname.lower()
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="URLs pointing to localhost are not allowed",
            )
        return
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="URLs pointing to private/internal networks are not allowed",
        )


@router.get("/evidence-types")
def curriculum_evidence_types(
    current_user: User = Depends(get_current_user),
):
    return CURRICULUM_EVIDENCE_TYPES


def infer_api_response_format(endpoint_url: str, content_type: str, requested: str) -> str:
    requested = (requested or "auto").lower()
    if requested in {"txt", "csv", "xlsx", "json"}:
        return requested
    suffix = Path(urlparse(endpoint_url).path).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".xlsx", ".xls"}:
        return "xlsx"
    if suffix == ".txt":
        return "txt"
    if "json" in content_type:
        return "json"
    if "csv" in content_type:
        return "csv"
    return "txt"


def api_filename(endpoint_url: str, response_format: str) -> str:
    parsed = urlparse(endpoint_url)
    name = Path(parsed.path).name or "curriculum-api-response"
    extension = "txt" if response_format == "json" else response_format
    if extension in {"txt", "csv", "xlsx"}:
        name = f"{Path(name).stem or 'curriculum-api-response'}.{extension}"
    elif "." not in name:
        name = f"{name}.txt"
    return name


def json_text(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def classify_curriculum_link(url: str, title: str) -> Dict[str, object]:
    text = f"{url} {title}".lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    source_format = suffix.lstrip(".") if suffix in {".pdf", ".csv", ".xlsx", ".xls", ".json", ".txt"} else "html"
    rules = [
        ("module_guide", ["module guide", "module descriptor", "study guide", "syllabus"], 0.9),
        ("curriculum_map", ["curriculum map", "programme map", "course map"], 0.88),
        ("qualification_standard", ["qualification standard", "heqsf", "saqa", "qualification"], 0.84),
        ("prospectus", ["prospectus", "undergraduate", "course-details", "courses"], 0.78),
        ("programme_page", ["programme", "diploma", "degree", "faculty", "department"], 0.68),
    ]
    for document_type, markers, confidence in rules:
        if any(marker in text for marker in markers):
            return {
                "source_format": source_format,
                "document_type": document_type,
                "confidence_score": confidence,
                "reason": f"Matched {document_type.replace('_', ' ')} keyword.",
            }
    if source_format == "pdf":
        return {
            "source_format": source_format,
            "document_type": "curriculum_pdf_candidate",
            "confidence_score": 0.58,
            "reason": "PDF discovered on curriculum source page.",
        }
    return {
        "source_format": source_format,
        "document_type": "general_curriculum_page",
        "confidence_score": 0.45,
        "reason": "General page discovered from curriculum source.",
    }


def extract_html_title(html: str) -> Optional[str]:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def extract_anchor_candidates(html: str, base_url: str, max_links: int, same_domain_only: bool) -> List[Dict[str, str]]:
    base_domain = urlparse(base_url).netloc
    candidates = []
    seen = set()
    for match in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        url = urljoin(base_url, href)
        if same_domain_only and urlparse(url).netloc != base_domain:
            continue
        title = re.sub(r"<[^>]+>", " ", match.group(2))
        title = re.sub(r"\s+", " ", title).strip() or Path(urlparse(url).path).name or url
        if url in seen:
            continue
        seen.add(url)
        candidates.append({"url": url, "title": title})
        if len(candidates) >= max_links:
            break
    return candidates


@router.post(
    "/sources/discover",
    response_model=CurriculumDiscoveryResponse,
)
def discover_curriculum_sources(
    payload: CurriculumDiscoveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    _validate_url_not_internal(payload.start_url)
    parsed_start = urlparse(payload.start_url)
    allow_unverified_tls = parsed_start.hostname in {"cput.ac.za", "www.cput.ac.za"}
    if allow_unverified_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    try:
        response = requests.get(
            payload.start_url,
            timeout=15,
            headers={"User-Agent": "PCLMAS-CurriculumDiscovery/1.0"},
            verify=not allow_unverified_tls,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Curriculum source discovery failed: {exc}",
        ) from exc

    html = response.text
    page_title = extract_html_title(html)
    links = extract_anchor_candidates(
        html=html,
        base_url=payload.start_url,
        max_links=payload.max_links,
        same_domain_only=payload.same_domain_only,
    )
    candidates = []
    for link in links:
        classification = classify_curriculum_link(link["url"], link["title"])
        if classification["confidence_score"] < 0.5 and not any(
            word in f"{link['url']} {link['title']}".lower()
            for word in ["course", "programme", "module", "curriculum", "prospectus", "qualification", "faculty"]
        ):
            continue
        candidates.append({**link, **classification})

    return {
        "start_url": payload.start_url,
        "institution": payload.institution,
        "page_title": page_title,
        "candidates": sorted(candidates, key=lambda item: item["confidence_score"], reverse=True),
        "total_candidates": len(candidates),
    }


@router.post(
    "/documents/upload",
    response_model=CurriculumUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_curriculum_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    faculty: Optional[str] = Form(default=None),
    department: Optional[str] = Form(default=None),
    programme: Optional[str] = Form(default=None),
    document_key: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    evidence_type: Optional[str] = Form(default=None),
    evidence_year: Optional[int] = Form(default=None),
    currency_status: str = Form(default="unknown"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    allowed_suffixes = {".pdf", ".docx", ".txt", ".csv", ".xlsx"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, DOCX, TXT, CSV, and XLSX curriculum uploads are supported",
        )
    if currency_status not in {"current", "historical", "expired", "unknown", "unverified"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid curriculum evidence currency status",
        )
    if evidence_year is not None and not 1900 <= evidence_year <= 2100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Evidence year must be between 1900 and 2100",
        )

    file_bytes = await file.read()

    staging_path = None
    try:
        staging_path = stage_curriculum_upload(
            file_bytes=file_bytes,
            original_filename=file.filename or "curriculum.pdf",
        )
        operational_job, _ = operational_job_service.enqueue(
            db=db,
            job_type="ingestion.curriculum_upload",
            requested_by=current_user.identity_id,
            parameters={
                "tenant_id": str(current_user.tenant_id),
                "staging_token": staging_path.name,
                "original_filename": file.filename or "curriculum.pdf",
                "mime_type": file.content_type,
                "actor_type": current_user.identity_type,
                "title": title,
                "faculty": faculty,
                "department": department,
                "programme": programme,
                "document_key": document_key,
                "description": description,
                "metadata": {
                    **({"declared_evidence_type": evidence_type} if evidence_type else {}),
                    "evidence_year": evidence_year,
                    "currency_status": currency_status,
                    "decision_use_allowed": currency_status == "current",
                },
            },
        )
    except ValueError as exc:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        raise

    return {
        "message": "Curriculum document accepted for durable processing",
        "operational_job": operational_job_service.to_dict(operational_job),
    }


@router.post(
    "/documents/import-api",
    response_model=CurriculumUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_curriculum_from_api(
    payload: CurriculumApiImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    if not payload.endpoint_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="API endpoint must start with http:// or https://",
        )
    _validate_url_not_internal(payload.endpoint_url)
    if payload.requires_credentials and (not payload.username or not payload.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Username and password are required when credentials are enabled",
        )

    auth = (payload.username, payload.password) if payload.requires_credentials else None
    try:
        response = requests.get(
            payload.endpoint_url,
            auth=auth,
            timeout=30,
            headers={"Accept": "application/json,text/csv,text/plain,*/*"},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Curriculum API request failed: {exc}",
        ) from exc

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    response_format = infer_api_response_format(
        payload.endpoint_url,
        content_type,
        payload.response_format,
    )
    filename = api_filename(payload.endpoint_url, response_format)
    file_bytes = response.content
    if response_format == "json":
        try:
            parsed = response.json()
            file_bytes = json_text(parsed).encode("utf-8")
            filename = filename.rsplit(".", 1)[0] + ".txt"
            content_type = "text/plain"
        except ValueError:
            logger.warning("[CURRICULUM] Failed to parse API response as JSON, using raw content")

    staging_path = None
    safe_endpoint_url = sanitised_endpoint_url(payload.endpoint_url)
    try:
        staging_path = stage_curriculum_upload(file_bytes, filename)
        operational_job, _ = operational_job_service.enqueue(
            db=db,
            job_type="ingestion.curriculum_upload",
            requested_by=current_user.identity_id,
            parameters={
                "tenant_id": str(current_user.tenant_id),
                "staging_token": staging_path.name,
                "original_filename": filename,
                "mime_type": content_type,
                "actor_type": current_user.identity_type,
                "title": payload.title or f"API import - {safe_endpoint_url}",
                "faculty": payload.faculty,
                "department": payload.department,
                "programme": payload.programme,
                "document_key": payload.document_key,
                "description": payload.description,
                "metadata": {
                    "source_type": "api",
                    "endpoint_url": safe_endpoint_url,
                    "requires_credentials": payload.requires_credentials,
                    "response_format": response_format,
                    "http_status": response.status_code,
                },
            },
        )
    except ValueError as exc:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        raise

    return {
        "message": "Curriculum API response accepted for durable processing",
        "operational_job": operational_job_service.to_dict(operational_job),
    }


@router.get("/cput-prospectus/courses")
def list_cput_prospectus_courses(
    faculty_code: str = "220",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    code = (faculty_code or "220").strip()
    if not code.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Faculty code must be numeric, for example 220 for Informatics and Design",
        )
    try:
        _html, links = cput_prospectus_connector.discover_courses(code)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"CPUT prospectus request failed: {exc}",
        ) from exc
    return {
        "faculty_code": code,
        "courses": [link.__dict__ for link in links],
        "course_codes": [link.course_code for link in links],
    }

@router.post(
    "/import/cput-prospectus",
    response_model=CPUTProspectusImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def import_cput_prospectus(
    payload: CPUTProspectusImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    faculty_code = (payload.faculty_code or "220").strip()
    if not faculty_code.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Faculty code must be numeric, for example 220 for Informatics and Design",
        )
    max_courses = payload.max_courses
    if max_courses is not None and (max_courses < 1 or max_courses > 200):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="max_courses must be between 1 and 200",
        )
    course_codes = [code.strip().upper() for code in (payload.course_codes or []) if code.strip()]
    invalid_codes = [code for code in course_codes if not code.replace("_", "").isalnum()]
    if invalid_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Course codes must be alphanumeric values such as DPICTA",
        )

    operational_job, _ = operational_job_service.enqueue(
        db=db,
        job_type="ingestion.cput_prospectus",
        requested_by=current_user.identity_id,
        parameters={
            "tenant_id": str(current_user.tenant_id),
            "faculty_code": faculty_code,
            "max_courses": max_courses,
            "course_codes": course_codes,
        },
    )
    return {
        "message": "CPUT prospectus import accepted for durable processing",
        "faculty_code": faculty_code,
        "operational_job": operational_job_service.to_dict(operational_job),
    }


@router.get(
    "/documents",
    response_model=List[CurriculumDocumentResponse],
)
def list_curriculum_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        scope_query(db.query(CurriculumDocument), CurriculumDocument, current_user)
        .order_by(CurriculumDocument.updated_at.desc())
        .limit(200)
        .all()
    )


@router.get(
    "/hierarchy",
    response_model=CurriculumHierarchyResponse,
)
def get_curriculum_hierarchy(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "faculties": db.query(AcademicFaculty).order_by(AcademicFaculty.name.asc()).all(),
        "departments": db.query(AcademicDepartment).order_by(AcademicDepartment.name.asc()).all(),
        "programmes": db.query(AcademicProgramme).order_by(AcademicProgramme.name.asc()).all(),
        "modules": db.query(CurriculumModule).filter(CurriculumModule.is_active.is_(True)).order_by(CurriculumModule.module_code.asc()).limit(5000).all(),
    }


@router.get("/quality/summary")
def curriculum_quality_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return curriculum_quality_service.summary(db)


@router.get(
    "/documents/{document_id}",
    response_model=CurriculumDocumentDetailResponse,
)
def get_curriculum_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(CurriculumDocument)
        .filter(CurriculumDocument.document_id == document_id)
        .first()
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curriculum document not found",
        )
    assert_entity_access(document, current_user)

    versions = (
        db.query(CurriculumDocumentVersion)
        .filter(CurriculumDocumentVersion.document_id == document.document_id)
        .order_by(CurriculumDocumentVersion.version_number.desc())
        .all()
    )

    return {
        "document": document,
        "versions": versions,
    }


@router.get(
    "/documents/{document_id}/versions",
    response_model=List[CurriculumDocumentVersionResponse],
)
def list_curriculum_document_versions(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(CurriculumDocument)
        .filter(CurriculumDocument.document_id == document_id)
        .first()
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curriculum document not found",
        )
    assert_entity_access(document, current_user)

    return (
        db.query(CurriculumDocumentVersion)
        .filter(CurriculumDocumentVersion.document_id == document.document_id)
        .order_by(CurriculumDocumentVersion.version_number.desc())
        .all()
    )


@router.get(
    "/documents/{document_id}/versions/compare",
    response_model=CurriculumVersionComparisonResponse,
)
def compare_curriculum_versions(
    document_id: UUID,
    from_version_id: UUID,
    to_version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = (
        db.query(CurriculumDocument)
        .filter(CurriculumDocument.document_id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curriculum document not found",
        )
    assert_entity_access(document, current_user)

    versions = (
        db.query(CurriculumDocumentVersion)
        .filter(
            CurriculumDocumentVersion.document_id == document_id,
            CurriculumDocumentVersion.version_id.in_([from_version_id, to_version_id]),
        )
        .all()
    )
    by_id = {version.version_id: version for version in versions}
    from_version = by_id.get(from_version_id)
    to_version = by_id.get(to_version_id)
    if not from_version or not to_version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both curriculum versions were not found",
        )

    from_chunks = chunks_for_version(db, from_version_id)
    to_chunks = chunks_for_version(db, to_version_id)
    from_hashes = {chunk.content_hash for chunk in from_chunks}
    to_hashes = {chunk.content_hash for chunk in to_chunks}
    from_text = "\n".join(chunk.content for chunk in from_chunks)
    to_text = "\n".join(chunk.content for chunk in to_chunks)

    return {
        "document_id": document_id,
        "from_version_id": from_version_id,
        "to_version_id": to_version_id,
        "from_version_number": from_version.version_number,
        "to_version_number": to_version.version_number,
        "chunk_count_delta": len(to_chunks) - len(from_chunks),
        "added_chunk_hashes": sorted(to_hashes - from_hashes),
        "removed_chunk_hashes": sorted(from_hashes - to_hashes),
        "shared_chunk_hash_count": len(from_hashes & to_hashes),
        "section_changes": compare_counts(
            count_metadata(from_chunks, "section"),
            count_metadata(to_chunks, "section"),
        ),
        "outcome_type_changes": compare_counts(
            count_metadata(from_chunks, "outcome_type"),
            count_metadata(to_chunks, "outcome_type"),
        ),
        "module_changes": compare_counts(
            count_metadata(from_chunks, "module_code"),
            count_metadata(to_chunks, "module_code"),
        ),
        "skill_coverage_changes": compare_skill_coverage(db, from_chunks, to_chunks),
        "text_diff": list(difflib.unified_diff(
            from_text.splitlines(),
            to_text.splitlines(),
            fromfile=f"v{from_version.version_number}",
            tofile=f"v{to_version.version_number}",
            lineterm="",
            n=2,
        ))[:300],
    }


@router.get(
    "/versions/{version_id}/chunks",
    response_model=List[DocumentChunkResponse],
)
def list_document_chunks(
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    version = (
        db.query(CurriculumDocumentVersion)
        .filter(CurriculumDocumentVersion.version_id == version_id)
        .first()
    )

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curriculum document version not found",
        )

    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.version_id == version.version_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(1000)
        .all()
    )


def chunks_for_version(db: Session, version_id: UUID) -> List[DocumentChunk]:
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.version_id == version_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )


def count_metadata(chunks: List[DocumentChunk], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for chunk in chunks:
        value = (chunk.chunk_metadata or {}).get(key) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def compare_counts(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, Dict[str, int]]:
    keys = sorted(set(before) | set(after))
    return {
        key: {
            "from": before.get(key, 0),
            "to": after.get(key, 0),
            "delta": after.get(key, 0) - before.get(key, 0),
        }
        for key in keys
    }


def compare_skill_coverage(
    db: Session,
    from_chunks: List[DocumentChunk],
    to_chunks: List[DocumentChunk],
) -> Dict[str, object]:
    from_ids = [chunk.chunk_id for chunk in from_chunks]
    to_ids = [chunk.chunk_id for chunk in to_chunks]
    from_skills = skill_ids_for_chunks(db, from_ids)
    to_skills = skill_ids_for_chunks(db, to_ids)
    return {
        "from_skill_count": len(from_skills),
        "to_skill_count": len(to_skills),
        "added_skill_ids": sorted(str(item) for item in (to_skills - from_skills)),
        "removed_skill_ids": sorted(str(item) for item in (from_skills - to_skills)),
        "shared_skill_count": len(from_skills & to_skills),
    }


def skill_ids_for_chunks(db: Session, chunk_ids: List[UUID]) -> set:
    if not chunk_ids:
        return set()
    rows = (
        db.query(SkillMapping.skill_id)
        .filter(
            SkillMapping.source_domain == "curriculum",
            SkillMapping.source_entity_type == "document_chunk",
            SkillMapping.source_entity_id.in_(chunk_ids),
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


def _evidence_review_dict(review: CurriculumEvidenceReview) -> Dict[str, object]:
    return {
        "review_id": str(review.review_id),
        "document_id": str(review.document_id),
        "version_id": str(review.version_id),
        "decision": review.decision,
        "source_authoritative": review.source_authoritative,
        "extraction_complete": review.extraction_complete,
        "module_evidence_complete": review.module_evidence_complete,
        "learning_outcomes_complete": review.learning_outcomes_complete,
        "completeness_score": review.completeness_score,
        "issue_codes": review.issue_codes or [],
        "notes": review.notes,
        "reviewer_id": review.reviewer_id,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


@router.get("/evidence-reviews/queue")
def curriculum_evidence_review_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    documents = (
        scope_query(db.query(CurriculumDocument), CurriculumDocument, current_user)
        .order_by(CurriculumDocument.updated_at.desc())
        .limit(200)
        .all()
    )
    items = []
    counts = {"unreviewed": 0, "validated": 0, "changes_required": 0, "rejected": 0}
    for document in documents:
        version = (
            db.query(CurriculumDocumentVersion)
            .filter(CurriculumDocumentVersion.document_id == document.document_id)
            .order_by(CurriculumDocumentVersion.version_number.desc())
            .first()
        )
        if not version:
            continue
        latest_review = (
            db.query(CurriculumEvidenceReview)
            .filter(CurriculumEvidenceReview.version_id == version.version_id)
            .order_by(CurriculumEvidenceReview.created_at.desc())
            .first()
        )
        review_count = (
            db.query(CurriculumEvidenceReview)
            .filter(CurriculumEvidenceReview.version_id == version.version_id)
            .count()
        )
        review_status = latest_review.decision if latest_review else "unreviewed"
        counts[review_status] = counts.get(review_status, 0) + 1
        metadata = version.extraction_metadata or {}
        suggested_issues = []
        if version.extraction_status != "completed":
            suggested_issues.append("extraction_not_completed")
        if not version.chunk_count:
            suggested_issues.append("no_extracted_evidence")
        if not document.programme:
            suggested_issues.append("programme_missing")
        items.append(
            {
                "document_id": str(document.document_id),
                "version_id": str(version.version_id),
                "title": document.title,
                "programme": document.programme,
                "faculty": document.faculty,
                "version_number": version.version_number,
                "original_filename": version.original_filename,
                "extraction_status": version.extraction_status,
                "page_count": version.page_count,
                "chunk_count": version.chunk_count,
                "content_hash": version.content_hash,
                "declared_evidence_type": metadata.get("declared_evidence_type"),
                "review_status": review_status,
                "review_count": review_count,
                "latest_review": _evidence_review_dict(latest_review) if latest_review else None,
                "suggested_issue_codes": suggested_issues,
            }
        )
    return {"items": items, "counts": counts, "total": len(items)}


@router.get("/versions/{version_id}/evidence-reviews")
def curriculum_evidence_review_history(
    version_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    reviews = (
        db.query(CurriculumEvidenceReview)
        .filter(CurriculumEvidenceReview.version_id == version_id)
        .order_by(CurriculumEvidenceReview.created_at.desc())
        .all()
    )
    return {"reviews": [_evidence_review_dict(review) for review in reviews]}


@router.post("/versions/{version_id}/evidence-reviews", status_code=status.HTTP_201_CREATED)
def submit_curriculum_evidence_review(
    version_id: UUID,
    payload: CurriculumEvidenceReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN", "ANALYST", "DATA_SCIENTIST")),
):
    version = db.query(CurriculumDocumentVersion).filter(
        CurriculumDocumentVersion.version_id == version_id
    ).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum version not found")
    if payload.decision == "validated" and not all(
        [
            payload.source_authoritative,
            payload.extraction_complete,
            payload.module_evidence_complete,
            payload.learning_outcomes_complete,
            payload.completeness_score >= 80,
        ]
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Validated evidence requires all four checks and a completeness score of at least 80",
        )
    review = CurriculumEvidenceReview(
        document_id=version.document_id,
        version_id=version.version_id,
        decision=payload.decision,
        source_authoritative=payload.source_authoritative,
        extraction_complete=payload.extraction_complete,
        module_evidence_complete=payload.module_evidence_complete,
        learning_outcomes_complete=payload.learning_outcomes_complete,
        completeness_score=payload.completeness_score,
        issue_codes=sorted(set(payload.issue_codes)),
        notes=payload.notes.strip(),
        reviewer_id=current_user.identity_id,
    )
    db.add(review)
    db.flush()
    log_audit_event(
        db=db,
        event_layer="application",
        event_type="curriculum_evidence_review",
        actor_type=current_user.identity_type,
        actor_id=current_user.identity_id,
        token_id=None,
        source_component="curriculum.api",
        action="submit_evidence_review",
        result="success",
        metadata={
            "review_id": str(review.review_id),
            "document_id": str(version.document_id),
            "version_id": str(version.version_id),
            "decision": payload.decision,
            "completeness_score": payload.completeness_score,
        },
    )
    db.commit()
    db.refresh(review)
    return _evidence_review_dict(review)










