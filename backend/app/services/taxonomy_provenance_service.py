"""Taxonomy provenance, coverage, and explainability reporting."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.data.taxonomy_source_registry import (
    ACA_INSPECTION,
    DHET_OFO_2021_PROFILE,
    OFO_INSPECTION,
    TAXONOMY_PROVENANCE,
)
from app.models.dhet_ofo import DHETOFOAcquisition, OFOEvidenceMapping
from app.models.esco_bundle import ESCOBundle
from app.models.esco_occupation import ESCOOccupation, ESCOOccupationSkillLink
from app.models.esco_skill import ESCOSkill
from app.models.ofo_taxonomy import OFOOccupation, OFOOccupationSkillLink, OFOSkill
from app.models.skill import Skill
from app.models.skill_mapping import SkillMapping
from app.models.skill_mapping_review_event import SkillMappingReviewEvent

logger = logging.getLogger(__name__)


def _dhet_acquisition_dict(row: DHETOFOAcquisition) -> Dict[str, Any]:
    return {
        "acquisition_id": str(row.acquisition_id),
        "method": row.method,
        "url": row.url,
        "resolved_url": row.resolved_url,
        "version": row.version,
        "acquisition_type": row.acquisition_type,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "http_status": row.http_status,
        "content_type": row.content_type,
        "byte_size": row.byte_size,
        "sha256": row.sha256,
        "file_name": row.file_name,
        "operator_id": row.operator_id,
        "operator_confirmed": row.operator_confirmed,
        "status": row.status,
        "validation_errors": row.validation_errors or [],
        "note": row.note,
        "data_rows": row.data_rows,
        "imported_rows": row.imported_rows,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _latest_acquisition(session: Session) -> Optional[DHETOFOAcquisition]:
    return (
        session.query(DHETOFOAcquisition)
        .order_by(DHETOFOAcquisition.created_at.desc())
        .first()
    )


def build_taxonomy_provenance(session: Session) -> Dict[str, Any]:
    total_skills = session.query(func.count(Skill.skill_id)).scalar() or 0
    active_skills = (
        session.query(func.count(Skill.skill_id))
        .filter(Skill.status == "active")
        .scalar()
        or 0
    )

    esco_total = session.query(func.count(ESCOSkill.esco_skill_id)).scalar() or 0
    esco_linked = (
        session.query(func.count(ESCOSkill.esco_skill_id))
        .filter(ESCOSkill.skill_id.isnot(None))
        .scalar()
        or 0
    )
    esco_versions = {
        row[0]: row[1]
        for row in session.query(
            ESCOSkill.taxonomy_version,
            func.count(ESCOSkill.esco_skill_id),
        )
        .group_by(ESCOSkill.taxonomy_version)
        .all()
    }

    esco_occupations = session.query(func.count(ESCOOccupation.esco_occupation_id)).scalar() or 0
    esco_occ_skill_links = (
        session.query(func.count(ESCOOccupationSkillLink.link_id)).scalar() or 0
    )

    ofo_occupations = session.query(func.count(OFOOccupation.ofo_occupation_id)).scalar() or 0
    ofo_skills = session.query(func.count(OFOSkill.ofo_skill_id)).scalar() or 0
    ofo_skill_linked = (
        session.query(func.count(OFOSkill.ofo_skill_id))
        .filter(OFOSkill.skill_id.isnot(None))
        .scalar()
        or 0
    )
    ofo_occ_skill_links = (
        session.query(func.count(OFOOccupationSkillLink.link_id)).scalar() or 0
    )

    ofo_occupations_by_version = {
        row[0]: int(row[1])
        for row in session.query(
            OFOOccupation.taxonomy_version,
            func.count(OFOOccupation.ofo_occupation_id),
        )
        .group_by(OFOOccupation.taxonomy_version)
        .all()
    }

    latest_acquired = _latest_acquisition(session)
    imported_official = (
        session.query(DHETOFOAcquisition)
        .filter(
            DHETOFOAcquisition.status == "imported",
            DHETOFOAcquisition.acquisition_type == "official",
        )
        .order_by(DHETOFOAcquisition.created_at.desc())
        .first()
    )
    imported_synthetic = (
        session.query(DHETOFOAcquisition)
        .filter(
            DHETOFOAcquisition.status == "imported",
            DHETOFOAcquisition.acquisition_type == "synthetic_fixture",
        )
        .order_by(DHETOFOAcquisition.created_at.desc())
        .first()
    )
    if imported_official is not None:
        ofo_source: Dict[str, Any] = {
            "status": "imported",
            "source": (
                "DHET (Department of Higher Education and Training) - official "
                "Skills Development source (Organising Framework for Occupations)"
            ),
            "version": imported_official.version,
            "acquisition_type": imported_official.acquisition_type,
            "licence": DHET_OFO_2021_PROFILE.get("licence_note"),
            "source_page_url": DHET_OFO_2021_PROFILE.get("source_page_url"),
            "resolved_url": imported_official.resolved_url,
            "sha256": imported_official.sha256,
            "byte_size": imported_official.byte_size,
            "retrieved_at": imported_official.retrieved_at.isoformat()
            if imported_official.retrieved_at
            else None,
            "recorded_at": imported_official.created_at.isoformat()
            if imported_official.created_at
            else None,
            "reason": None,
        }
    else:
        ofo_source = dict(OFO_INSPECTION)
        if imported_synthetic is not None:
            ofo_source["status"] = "demo_fixture"
            ofo_source["reason"] = (
                "Only the 5-row synthetic demo fixture has been imported. It is tagged "
                "synthetic_fixture and is never presented as the official DHET OFO 2021. "
                "OFO remains deferred until an official acquisition is validated and imported."
            )

    imported_esco_bundle = (
        session.query(ESCOBundle)
        .filter(ESCOBundle.status == "imported")
        .order_by(ESCOBundle.created_at.desc())
        .first()
    )
    if imported_esco_bundle is not None:
        esco_source: Dict[str, Any] = {
            "status": "imported",
            "source": imported_esco_bundle.source_label,
            "version": imported_esco_bundle.source_version,
            "acquisition_type": "official_bundle",
            "licence": imported_esco_bundle.licence,
            "source_url": imported_esco_bundle.source_url,
            "bundle_id": str(imported_esco_bundle.bundle_id),
            "run_id": imported_esco_bundle.run_id,
            "files": imported_esco_bundle.files or [],
            "file_count": len(imported_esco_bundle.files or []),
            "expected_file_count": len(imported_esco_bundle.expected_files or []),
            "row_counts": imported_esco_bundle.row_counts or {},
            "imported_counts": imported_esco_bundle.imported_counts or {},
            "not_modelled_files": imported_esco_bundle.not_modelled_files or [],
            "imported_at": imported_esco_bundle.imported_at.isoformat()
            if imported_esco_bundle.imported_at
            else None,
            "recorded_at": imported_esco_bundle.created_at.isoformat()
            if imported_esco_bundle.created_at
            else None,
            "reason": None,
        }
    else:
        esco_source = ACA_INSPECTION

    mappings_total = session.query(func.count(SkillMapping.mapping_id)).scalar() or 0

    status_rows = (
        session.query(
            SkillMapping.mapping_status,
            func.count(SkillMapping.mapping_id),
        )
        .group_by(SkillMapping.mapping_status)
        .all()
    )
    mapping_status_counts = {status: int(count) for status, count in status_rows}

    approved = mapping_status_counts.get("approved", 0)
    approved_auto_rows = (
        session.query(SkillMapping.mapping_id, SkillMapping.mapping_metadata)
        .filter(SkillMapping.mapping_status == "approved")
        .all()
    )
    auto_approved = sum(
        1
        for _mapping_id, metadata in approved_auto_rows
        if (metadata or {}).get("auto_review")
    )
    rejected = mapping_status_counts.get("rejected", 0)
    candidate = mapping_status_counts.get("candidate", 0)
    needs_review = mapping_status_counts.get("needs_review", 0)
    deferred = mapping_status_counts.get("deferred", 0)
    unresolved = candidate + needs_review

    esco_linked_canonical = (
        session.query(func.count(func.distinct(ESCOSkill.skill_id)))
        .filter(ESCOSkill.skill_id.isnot(None))
        .scalar()
        or 0
    )
    ofo_linked_canonical = (
        session.query(func.count(func.distinct(OFOEvidenceMapping.canonical_skill_id)))
        .filter(
            OFOEvidenceMapping.canonical_skill_id.isnot(None),
            OFOEvidenceMapping.mapping_status == "approved",
        )
        .scalar()
        or 0
    )

    review_event_count = session.query(func.count(SkillMappingReviewEvent.review_event_id)).scalar() or 0

    counts = {
        "active_skills": active_skills,
        "total_skills": total_skills,
        "esco_total": esco_total,
        "esco_linked_canonical_skills": int(esco_linked_canonical),
        "esco_versions": esco_versions,
        "esco_occupations": esco_occupations,
        "esco_occupation_skill_links": esco_occ_skill_links,
        "ofo_occupations": ofo_occupations,
        "ofo_skills": ofo_skills,
        "ofo_linked_canonical_skills": int(ofo_linked_canonical),
        "ofo_occupation_skill_links": ofo_occ_skill_links,
        "ofo_occupation_by_version": ofo_occupations_by_version,
        "mappings_total": mappings_total,
    }

    def _ratio(num: int, denom: int) -> float:
        return round(num / denom, 4) if denom else 0.0

    coverage = {
        "esco_skill_coverage": _ratio(esco_linked_canonical, active_skills),
        "ofo_skill_coverage": _ratio(ofo_linked_canonical, active_skills),
        "ofo_deferred_reason": ofo_source.get("reason"),
        "ofo_version": ofo_source.get("version"),
    }

    mapping_status_summary = {
        "approved": approved,
        "auto_approved": int(auto_approved),
        "candidate": candidate,
        "needs_review": needs_review,
        "rejected": rejected,
        "deferred": deferred,
        "unresolved": unresolved,
    }

    traceability = _build_traceability(session)

    acquisition_type_rows = (
        session.query(
            DHETOFOAcquisition.acquisition_type,
            func.count(DHETOFOAcquisition.acquisition_id),
        )
        .group_by(DHETOFOAcquisition.acquisition_type)
        .all()
    )
    acquisition_type_counts = {
        str(row[0]): int(row[1]) for row in acquisition_type_rows
    }

    dhet_ofo_summary: Dict[str, Any] = {
        "profile": DHET_OFO_2021_PROFILE,
        "latest_acquisition": _dhet_acquisition_dict(latest_acquired) if latest_acquired else None,
        "acquisition_count": session.query(func.count(DHETOFOAcquisition.acquisition_id)).scalar() or 0,
        "acquisition_type_counts": acquisition_type_counts,
        "official_imported": imported_official is not None,
        "synthetic_imported": imported_synthetic is not None,
        "occupation_counts_by_version": ofo_occupations_by_version,
    }

    return {
        "sources": {
            "esco": esco_source,
            "ofo": ofo_source,
            "dhet_ofo": dhet_ofo_summary,
            "recorded_at": ACA_INSPECTION.get("recorded_at"),
        },
        "counts": counts,
        "coverage": coverage,
        "mapping_status_summary": mapping_status_summary,
        "review_event_count": review_event_count,
        "traceability": traceability,
    }


def _build_traceability(session: Session) -> List[Dict[str, Any]]:
    sample_mappings = (
        session.query(SkillMapping)
        .filter(SkillMapping.mapping_status == "approved")
        .order_by(SkillMapping.confidence_score.desc())
        .limit(5)
        .all()
    )
    chains: List[Dict[str, Any]] = []
    for mapping in sample_mappings:
        chains.append(
            {
                "mapping_id": str(mapping.mapping_id),
                "source_record_id": mapping.source_record_id,
                "extracted_text": mapping.matched_text,
                "canonical_skill_id": str(mapping.skill_id),
                "esco_skill_id": str(mapping.esco_skill_id) if mapping.esco_skill_id else None,
                "method": mapping.extraction_method,
                "confidence": mapping.confidence_score,
                "status": mapping.mapping_status,
                "review_decision": (mapping.mapping_metadata or {}).get("review", {}).get("decision"),
                "reviewer": mapping.reviewed_by,
            }
        )
    return chains


def build_taxonomy_report_payload(session: Session) -> Dict[str, Any]:
    provenance = build_taxonomy_provenance(session)
    return {
        "report_type": "taxonomy_provenance",
        "taxonomy_provenance": provenance,
    }


taxonomy_provenance_service = type("TaxonomyProvenanceService", (), {"build": staticmethod(build_taxonomy_provenance)})()
