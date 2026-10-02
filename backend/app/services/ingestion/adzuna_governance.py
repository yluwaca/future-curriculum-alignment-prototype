"""
Adzuna research-permission governance metadata.

Written academic research permission was received from Adzuna Support
(Jesse Mutenyo) on 2026-09-10. It approves use of the Adzuna South Africa
API for the CPUT academic study, permits trial access and retention for
thesis/analysis, and requires full attribution with a working link to
https://www.adzuna.co.za in any thesis, publication, research, or examiner
package. These fields travel with new ingestion runs, signals, demand
evidence and report exports.

The stable source key ``adzuna_jobs_api_trial`` and the acquisition label
``ADZUNA_TRIAL_NOT_EMPIRICAL`` are deliberately preserved so existing
records are not duplicated and historical acquisition metadata remains
auditable. New runs carry the approved permission metadata on top of that
identity.
"""

from typing import Any, Dict


ADZUNA_PERMISSION: Dict[str, Any] = {
    "permission_status": "written_academic_permission",
    "permission_received_at": "2026-09-10",
    "permission_scope": "academic_study_trial_access_and_retention",
    "empirical_use_permitted": True,
    "attribution_required": True,
    "attribution_url": "https://www.adzuna.co.za",
    "grantor": "Jesse Mutenyo, Adzuna Support",
    "evidence_path": "docs/evidence/adzuna-permission-2026-09-10.md",
}

ADZUNA_ATTRIBUTION_NOTE = (
    "Adzuna South Africa data used under written academic research permission. "
    "Source: https://www.adzuna.co.za"
)


def apply_adzuna_permission(source: Any) -> Any:
    """Stamp the approved permission onto a registered Adzuna data source.

    Merges the permission metadata and attribution note into the source's
    ``config`` JSONB and marks the source active and authorised. Idempotent:
    re-applying simply overwrites the same values.
    """
    config = dict(getattr(source, "config", None) or {})
    config["permission"] = {**(config.get("permission") or {}), **ADZUNA_PERMISSION}
    config["attribution_note"] = ADZUNA_ATTRIBUTION_NOTE
    source.config = config
    source.is_authorised = True
    if getattr(source, "status", None) != "active":
        source.status = "active"
    return source