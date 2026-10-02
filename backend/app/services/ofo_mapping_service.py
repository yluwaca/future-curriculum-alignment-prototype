"""
Evidence-based OFO 2021 mapping with append-only decision audit.

Guarantees the DHET handoff mapping invariants:

- A mapping is never assigned from a title-only string match. Evidence used for
  matching is the full advert/evidence plus duties, education, experience, and
  skills; every mapping records method, confidence, reviewer, and reason.
- When no defensible six-digit OFO occupation exists the mapping is left
  deferred/unresolved with an explicit reason.
- An approval requires a valid six-digit OFO code already present in the
  imported OFO tables, so codes are never fabricated.
- Human decisions (approved / rejected / deferred / needs_review /
  disagreement / resolved) persist an append-only review event plus an
  enterprise audit event.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.dhet_ofo import OFOEvidenceMapping, OFOEvidenceMappingReviewEvent
from app.models.ofo_taxonomy import OFOOccupation
from app.services.audit_service import log_audit_event

logger = logging.getLogger(__name__)

OFO_CODE6_RE = re.compile(r"^\d{6}$")

VALID_DECISIONS = ("approved", "rejected", "merged", "needs_review", "deferred", "disagreement", "resolved")

DECISION_RESULTING_STATUS = {
    "approved": "approved",
    "rejected": "rejected",
    "merged": "merged",
    "needs_review": "needs_review",
    "deferred": "deferred",
    "disagreement": "needs_review",
    "resolved": "approved",
}


class OFOMappingError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _evidence_confidence(query_tokens: set, occupation_tokens: set) -> float:
    if not query_tokens or not occupation_tokens:
        return 0.0
    inter = len(query_tokens & occupation_tokens)
    union = len(query_tokens | occupation_tokens)
    return round(inter / union, 4)


class OFOMappingService:
    CANDIDATE_THRESHOLD = 0.30
    TITLE_ONLY_EVIDENCE_MAX = 60

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Proposal
    # ------------------------------------------------------------------

    def propose(self, payload: Dict[str, Any], actor_id: Optional[str] = None) -> OFOEvidenceMapping:
        matched_text = (payload.get("matched_text") or "").strip()
        duties = (payload.get("duties_text") or "").strip()
        education = (payload.get("education_text") or "").strip()
        experience = (payload.get("experience_text") or "").strip()
        skills = (payload.get("skills_text") or "").strip()
        version = payload.get("version") or "2021"

        structured_evidence = bool(duties or education or experience or skills)
        title_only = (
            not structured_evidence
            and len(matched_text) <= self.TITLE_ONLY_EVIDENCE_MAX
            and len(_tokens(matched_text)) <= 6
        )

        mapping = OFOEvidenceMapping(
            source_record_id=payload.get("source_record_id"),
            source_domain=payload.get("source_domain") or "labour_market",
            source_entity_type=payload.get("source_entity_type"),
            matched_text=matched_text,
            duties_text=duties or None,
            education_text=education or None,
            experience_text=experience or None,
            skills_text=skills or None,
            canonical_skill_id=_optional_uuid(payload.get("canonical_skill_id")),
            version=version,
            method="title_only_probe" if title_only else "evidence_semantic",
            confidence_score=0.0 if title_only else None,
            mapping_status="deferred" if title_only else "candidate",
            mapping_metadata={
                "title_only": title_only,
                "title_only_reason": (
                    "Title-only evidence cannot produce a defensible OFO mapping. "
                    "OFO codes are never assigned from a title string alone; supply "
                    "duties, education, experience and skills evidence, or defer."
                )
                if title_only
                else None,
            },
        )

        if not title_only:
            query = " ".join([matched_text, duties, education, experience, skills])
            query_tokens = _tokens(query)
            candidates = (
                self.db.query(OFOOccupation)
                .filter(OFOOccupation.status == "active", OFOOccupation.taxonomy_version == version)
                .all()
            )
            best_code = None
            best_title = None
            best_score = 0.0
            for occ in candidates:
                score = _evidence_confidence(
                    query_tokens, _tokens(f"{occ.preferred_label} {occ.description or ''}")
                )
                if score > best_score:
                    best_score = score
                    best_code = occ.ofo_code
                    best_title = occ.preferred_label
            mapping.confidence_score = best_score
            if best_code and best_score >= self.CANDIDATE_THRESHOLD:
                mapping.ofo_occupation_id = self._occupation_id_by_code(best_code, version)
                mapping.ofo_code = best_code
                mapping.occupation_title = best_title
                mapping.mapping_status = "candidate"
            else:
                mapping.mapping_status = "deferred"
                mapping.mapping_metadata["defer_reason"] = (
                    "No defensible six-digit OFO mapping: the supplied evidence does not "
                    "reliably identify a single SA OFO 2021 occupation (best "
                    f"{'none' if best_code is None else best_code} @ "
                    f"{best_score:.3f}). Left unresolved/deferred."
                )
                mapping.confidence_score = best_score or 0.0
                mapping.method = "evidence_semantic"

        self.db.add(mapping)
        self.db.commit()
        self.db.refresh(mapping)
        self._audit_propose(mapping, actor_id)
        return mapping

    def _occupation_id_by_code(self, code: str, version: str) -> Optional[UUID]:
        row = (
            self.db.query(OFOOccupation)
            .filter(
                OFOOccupation.ofo_code == code,
                OFOOccupation.taxonomy_version == version,
            )
            .first()
        )
        return row.ofo_occupation_id if row else None

    def _audit_propose(self, mapping: OFOEvidenceMapping, actor_id: Optional[str]) -> None:
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="ofo_mapping_propose",
            actor_type="system",
            actor_id=actor_id,
            token_id=None,
            source_component="ofo_mapping_service",
            action="ofo_mapping_propose",
            result="success" if mapping.mapping_status != "deferred" else "deferred",
            metadata={
                "mapping_id": str(mapping.mapping_id),
                "method": mapping.method,
                "confidence": mapping.confidence_score,
                "title_only": (mapping.mapping_metadata or {}).get("title_only", False),
                "status": mapping.mapping_status,
                "version": mapping.version,
            },
        )

    # ------------------------------------------------------------------
    # Review
    # ------------------------------------------------------------------

    def review(
        self,
        mapping_id: UUID,
        decision: str,
        note: str,
        reviewer_id: Optional[str],
        selected_ofo_code: Optional[str] = None,
    ) -> OFOEvidenceMapping:
        if decision not in VALID_DECISIONS:
            raise OFOMappingError(f"Unknown review decision: {decision}.")
        mapping = self.db.query(OFOEvidenceMapping).filter(
            OFOEvidenceMapping.mapping_id == mapping_id
        ).first()
        if not mapping:
            raise OFOMappingError("OFO evidence mapping not found.", status_code=404)

        previous_status = mapping.mapping_status
        code_before = mapping.ofo_code

        title_only = bool((mapping.mapping_metadata or {}).get("title_only"))
        if title_only and decision != "deferred":
            raise OFOMappingError(
                "This is a title-only probe: it can never be approved, rejected, or "
                "resolved to an OFO code because no defensible evidence was supplied. "
                "Only 'deferred' is valid until full duties/education/experience/skills "
                "evidence is attached.",
                status_code=400,
            )

        code_after = selected_ofo_code.strip() if selected_ofo_code else None
        if code_after is not None and not OFO_CODE6_RE.match(code_after):
            raise OFOMappingError(
                f"Refused: '{code_after}' is not a valid six-digit OFO code. "
                "OFO codes are never fabricated.",
                status_code=400,
            )

        if decision == "approved":
            target_code = code_after or mapping.ofo_code
            if not target_code:
                raise OFOMappingError(
                    "An approved OFO mapping requires a defensible six-digit OFO code "
                    "that exists in the imported OFO 2021 tables. Defer instead rather "
                    "than fabricate a code.",
                    status_code=400,
                )
            occ = (
                self.db.query(OFOOccupation)
                .filter(
                    OFOOccupation.ofo_code == target_code,
                    OFOOccupation.taxonomy_version == (mapping.version or "2021"),
                )
                .first()
            )
            if not occ:
                raise OFOMappingError(
                    f"Refused: OFO code '{target_code}' does not exist in the imported "
                    "DHET OFO tables; approving it would fabricate a code.",
                    status_code=400,
                )
            code_after = target_code
            mapping.ofo_occupation_id = occ.ofo_occupation_id
            mapping.occupation_title = occ.preferred_label
        elif decision == "rejected":
            mapping.ofo_code = None
            mapping.ofo_occupation_id = None
            mapping.occupation_title = None
            code_after = None
        elif decision == "merged" and code_after is None:
            code_after = mapping.ofo_code if mapping.ofo_code else None

        resulting = DECISION_RESULTING_STATUS[decision]
        mapping.mapping_status = resulting
        mapping.reviewer_id = reviewer_id
        mapping.reviewed_at = func.now()
        mapping.review_note = note
        if code_after is not None:
            mapping.ofo_code = code_after
        metadata_snapshot = dict(mapping.mapping_metadata or {})
        metadata_snapshot["review"] = {"decision": decision, "resulting_status": resulting}
        metadata_snapshot["title_only"] = metadata_snapshot.get("title_only", False)
        mapping.mapping_metadata = metadata_snapshot

        event = OFOEvidenceMappingReviewEvent(
            mapping_id=mapping.mapping_id,
            previous_status=previous_status,
            decision=decision,
            reviewer_id=reviewer_id,
            note=note,
            ofo_code_before=code_before,
            ofo_code_after=code_after,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(mapping)

        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type=f"ofo_mapping_review_{decision}",
            actor_type="human",
            actor_id=reviewer_id,
            token_id=None,
            source_component="ofo_mapping_service",
            action=f"ofo_mapping_review_{decision}",
            result="success",
            metadata={
                "mapping_id": str(mapping.mapping_id),
                "previous_status": previous_status,
                "remaining_status": resulting,
                "decision": decision,
                "ofo_code_before": code_before,
                "ofo_code_after": code_after,
                "title_only": (mapping.mapping_metadata or {}).get("title_only", False),
            },
        )
        return mapping

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_mappings(
        self,
        status: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[OFOEvidenceMapping]:
        query = self.db.query(OFOEvidenceMapping)
        if status:
            query = query.filter(OFOEvidenceMapping.mapping_status == status)
        if search and len(search.strip()) >= 2:
            escaped = search.replace("%", "\\%").replace("_", "\\_")
            query = query.filter(OFOEvidenceMapping.matched_text.ilike(f"%{escaped}%"))
        return (
            query.order_by(OFOEvidenceMapping.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def summary(self) -> Dict[str, Any]:
        status_rows = (
            self.db.query(OFOEvidenceMapping.mapping_status, func.count(OFOEvidenceMapping.mapping_id))
            .group_by(OFOEvidenceMapping.mapping_status)
            .all()
        )
        status_counts = {status: int(count) for status, count in status_rows}
        return {
            "total": sum(status_counts.values()),
            "status_counts": status_counts,
            "title_only_probes": int(
                self.db.query(func.count(OFOEvidenceMapping.mapping_id))
                .filter(OFOEvidenceMapping.method == "title_only_probe")
                .scalar()
                or 0
            ),
        }

    def history(self, mapping_id: UUID) -> Dict[str, Any]:
        mapping = self.db.query(OFOEvidenceMapping).filter(
            OFOEvidenceMapping.mapping_id == mapping_id
        ).first()
        if not mapping:
            raise OFOMappingError("OFO evidence mapping not found.", status_code=404)
        events = (
            self.db.query(OFOEvidenceMappingReviewEvent)
            .filter(OFOEvidenceMappingReviewEvent.mapping_id == mapping_id)
            .order_by(OFOEvidenceMappingReviewEvent.created_at.asc())
            .all()
        )
        return {
            "mapping_id": str(mapping.mapping_id),
            "mapping_status": mapping.mapping_status,
            "ofo_code": mapping.ofo_code,
            "occupation_title": mapping.occupation_title,
            "history": [
                {
                    "review_event_id": str(event.review_event_id),
                    "previous_status": event.previous_status,
                    "decision": event.decision,
                    "reviewer_id": event.reviewer_id,
                    "note": event.note,
                    "ofo_code_before": event.ofo_code_before,
                    "ofo_code_after": event.ofo_code_after,
                    "timestamp": event.created_at.isoformat() if event.created_at else None,
                }
                for event in events
            ],
            "audit_ids": [str(event.review_event_id) for event in events],
        }


def _optional_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def ofo_mapping_service(db: Session) -> OFOMappingService:
    return OFOMappingService(db)