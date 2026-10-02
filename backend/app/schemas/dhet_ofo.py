"""
Request schemas for the DHET OFO 2021 acquisition and evidence-mapping APIs.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DHETOFODownloadRequest(BaseModel):
    """Controlled DHET OFO download.

    An explicit operator confirmation is mandatory before any file is written.
    ``resolved_url`` may be supplied by the operator from the official DHET
    Skills Development page; if omitted the last recorded discovery result is
    used. Only allowlisted DHET domains are followed.
    """

    resolved_url: Optional[str] = Field(default=None, max_length=1000)

    confirmed: bool = Field(default=False)

    note: Optional[str] = Field(default=None, max_length=2000)


class OFOEvidenceMappingProposeRequest(BaseModel):
    """Propose an OFO evidence mapping from full advert/evidence content.

    Structured evidence fields (duties, education, experience, skills) are
    required for a defensible mapping. When only a short title is supplied the
    proposal is recorded as a title-only probe and is never approved.
    """

    source_record_id: Optional[str] = Field(default=None, max_length=255)

    source_domain: str = Field(min_length=2, max_length=100)

    source_entity_type: Optional[str] = Field(default=None, max_length=100)

    matched_text: str = Field(default="", max_length=20000)

    duties_text: Optional[str] = Field(default=None, max_length=20000)

    education_text: Optional[str] = Field(default=None, max_length=20000)

    experience_text: Optional[str] = Field(default=None, max_length=20000)

    skills_text: Optional[str] = Field(default=None, max_length=20000)

    canonical_skill_id: Optional[str] = None

    version: str = Field(default="2021", pattern="^[0-9]{4}$")


class OFOEvidenceMappingReviewRequest(BaseModel):
    """Human review decision for an OFO evidence mapping.

    Decisions mirror the canonical skill-mapping vocabulary. An approval
    requires a defensible six-digit OFO code that exists in the imported OFO
    2021 tables; codes are never fabricated from title-only evidence.
    """

    decision: str = Field(
        pattern="^(approved|rejected|merged|needs_review|deferred|disagreement|resolved)$"
    )

    note: str = Field(min_length=10, max_length=5000)

    selected_ofo_code: Optional[str] = Field(default=None, max_length=20)

    reviewer_id: Optional[str] = Field(default=None, max_length=100)