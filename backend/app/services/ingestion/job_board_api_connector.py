"""
Job-board API ingestion profiles and simulator.

Live job-board access is partner-gated for sources such as LinkedIn and
Indeed.  This connector models their expected payloads now, accepts simulated
payloads, and normalises them through the same JobPosting path used by CSV/PDF
uploads.  When API access is granted, the HTTP fetch step can feed this service
without changing downstream storage.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests
from sqlalchemy.orm import Session

from app.models.data_source import DataSource
from app.services.ingestion.adzuna_governance import (
    ADZUNA_ATTRIBUTION_NOTE,
    ADZUNA_PERMISSION,
    apply_adzuna_permission,
)
from app.services.ingestion.job_advert_file_connector import job_advert_file_connector
from app.services.ingestion.job_advert_file_connector import stable_hash
from app.services.ingestion.job_service import ingestion_job_service


JOB_BOARD_PROFILES: Dict[str, Dict[str, Any]] = {
    "adzuna": {
        "source_key": "adzuna_jobs_api_trial",
        "name": "Adzuna Jobs API (academic research permission)",
        "base_url": "https://api.adzuna.com/v1/api/jobs/za/search/1",
        "record_type": "adzuna_job_payload",
        "required_fields": ["id", "title", "description", "created", "location"],
        "field_map": {
            "job_id": ["id"], "job_title": ["title"], "description": ["description"],
            "posted_date": ["created"], "source_url": ["redirect_url"],
            "employment_type": ["contract_type", "contract_time"],
            "salary_min": ["salary_min"], "salary_max": ["salary_max"],
        },
        "job_id_prefix": "ADZUNA-TRIAL-",
        "structured_location_fields": True,
    },
    "synthetic": {
        "source_key": "synthetic_jobs_api",
        "name": "Synthetic Job Board (automated test fixture)",
        "base_url": None,
        "record_type": "synthetic_job_payload",
        "required_fields": ["id", "title", "description", "created", "location"],
        "field_map": {
            "job_id": ["id"], "job_title": ["title"], "description": ["description"],
            "posted_date": ["created"], "source_url": ["redirect_url"],
            "employment_type": ["contract_type", "contract_time"],
            "salary_min": ["salary_min"], "salary_max": ["salary_max"],
        },
        "job_id_prefix": "SYNTHETIC-",
        "structured_location_fields": True,
    },
    "linkedin": {
        "source_key": "linkedin_jobs_api",
        "name": "LinkedIn Jobs API Payload",
        "base_url": "https://api.linkedin.com/rest",
        "record_type": "linkedin_job_payload",
        "required_fields": ["id", "title", "description", "listedAt", "location"],
        "field_map": {
            "job_id": ["id", "jobPostingId"],
            "job_title": ["title", "jobTitle"],
            "description": ["description", "descriptionText"],
            "company": ["companyName", "company"],
            "posted_date": ["listedAt", "postedAt", "createdAt"],
            "region": ["location", "formattedLocation"],
            "employment_type": ["employmentStatus", "employmentType"],
            "source_url": ["jobPostingUrl", "url"],
            "skills": ["skills", "requiredSkills"],
        },
    },
    "indeed": {
        "source_key": "indeed_jobs_api",
        "name": "Indeed Job Sync/API Payload",
        "base_url": "https://apis.indeed.com",
        "record_type": "indeed_job_payload",
        "required_fields": ["jobKey", "title", "description", "date", "location"],
        "field_map": {
            "job_id": ["jobKey", "id"],
            "job_title": ["title", "jobTitle"],
            "description": ["description", "snippet"],
            "company": ["company", "companyName"],
            "posted_date": ["date", "postedDate"],
            "region": ["location", "city"],
            "employment_type": ["jobType", "employmentType"],
            "source_url": ["url", "jobUrl"],
            "skills": ["skills", "taxonomyAttributes"],
        },
    },
    "pnet": {
        "source_key": "pnet_jobs_api",
        "name": "PNet Jobs API Payload",
        "base_url": None,
        "record_type": "pnet_job_payload",
        "required_fields": ["id", "title", "description", "location"],
        "field_map": {
            "job_id": ["id", "reference"],
            "job_title": ["title"],
            "description": ["description", "requirements"],
            "company": ["company", "companyName"],
            "posted_date": ["postedDate", "date"],
            "region": ["location", "province"],
            "employment_type": ["contractType", "employmentType"],
            "source_url": ["url"],
            "skills": ["skills", "keywords"],
        },
    },
    "careerjunction": {
        "source_key": "careerjunction_jobs_api",
        "name": "CareerJunction Jobs API Payload",
        "base_url": None,
        "record_type": "careerjunction_job_payload",
        "required_fields": ["id", "title", "description", "location"],
        "field_map": {
            "job_id": ["id", "reference"],
            "job_title": ["title"],
            "description": ["description", "requirements"],
            "company": ["company", "companyName"],
            "posted_date": ["postedDate", "date"],
            "region": ["location", "province"],
            "employment_type": ["jobType", "employmentType"],
            "source_url": ["url"],
            "skills": ["skills", "keywords"],
        },
    },
}


def _first(payload: Dict[str, Any], aliases: Iterable[str]) -> Any:
    for alias in aliases:
        if alias in payload and payload[alias] not in (None, ""):
            return payload[alias]
    return None


def _json_safe(payload: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))


class JobBoardAPIConnector:
    def provider_profile(self, provider: str) -> Dict[str, Any]:
        key = provider.lower().strip()
        if key not in JOB_BOARD_PROFILES:
            raise ValueError(f"Unsupported job-board provider: {provider}")
        return JOB_BOARD_PROFILES[key]

    def sample_contracts(self) -> Dict[str, Dict[str, Any]]:
        return {
            provider: {
                "record_type": profile["record_type"],
                "required_fields": profile["required_fields"],
                "field_map": profile["field_map"],
                "sample_payload": self.sample_payload(provider),
            }
            for provider, profile in JOB_BOARD_PROFILES.items()
        }

    def sample_payload(self, provider: str) -> Dict[str, Any]:
        profile = self.provider_profile(provider)
        if provider == "linkedin":
            return {
                "id": "linkedin-sample-001",
                "title": "Data Analyst",
                "companyName": "Example Employer",
                "description": "Analyse data using SQL, Python and dashboards.",
                "listedAt": datetime.now(timezone.utc).isoformat(),
                "location": "Cape Town, Western Cape",
                "employmentStatus": "Full-time",
                "skills": ["SQL", "Python", "Power BI"],
                "jobPostingUrl": "https://www.linkedin.com/jobs/view/sample",
            }
        if provider == "indeed":
            return {
                "jobKey": "indeed-sample-001",
                "title": "Software Developer",
                "company": "Example Employer",
                "description": "Build APIs with Python, SQL and cloud platforms.",
                "date": datetime.now(timezone.utc).isoformat(),
                "location": "Johannesburg, Gauteng",
                "jobType": "Permanent",
                "skills": ["Python", "REST APIs", "SQL"],
                "url": "https://www.indeed.com/viewjob?jk=sample",
            }
        if provider == "synthetic":
            return {
                "id": "syn-sample-001",
                "title": "Data Engineer",
                "company": {"display_name": "Synthetic Employer"},
                "description": "Build data pipelines with Python, SQL and AWS cloud.",
                "created": datetime.now(timezone.utc).isoformat(),
                "redirect_url": "https://example.invalid/synthetic/syn-sample-001",
                "location": {"display_name": "Cape Town, Western Cape", "area": ["Cape Town"]},
                "category": {"label": "IT Jobs"},
                "contract_type": "full_time",
                "salary_min": 60000,
                "salary_max": 95000,
            }
        return {
            "id": f"{provider}-sample-001",
            "title": "ICT Support Specialist",
            "company": "Example Employer",
            "description": "Support networks, service desk operations and security controls.",
            "postedDate": datetime.now(timezone.utc).isoformat(),
            "location": "South Africa",
            "employmentType": "Full-time",
            "skills": ["Networking", "IT support", "Cybersecurity"],
            "url": f"https://example.invalid/{profile['source_key']}/sample",
        }

    def ensure_source(self, db: Session, provider: str, tenant_id: Optional[str] = None) -> DataSource:
        profile = self.provider_profile(provider)
        source_key = profile["source_key"] if not tenant_id else f"{profile['source_key']}_{tenant_id}"
        defaults = {
            "tenant_id": tenant_id,
            "name": profile["name"],
            "source_type": "current_jobs",
            "source_category": "labour_market",
            "connector_type": f"{provider}_job_board_api",
            "source_scope": "tenant" if tenant_id else "shared",
            "ingestion_mode": "streaming",
            "source_format": "json_api",
            "base_url": profile.get("base_url"),
            "refresh_policy": "manual",
            "is_authorised": True if provider == "adzuna" else False,
            "config": {
                "provider": provider,
                "payload_contract": {
                    "record_type": profile["record_type"],
                    "required_fields": profile["required_fields"],
                    "field_map": profile["field_map"],
                },
                "pagination": {"strategy": "cursor_or_page", "max_pages": 1},
                "rate_limit": {"requests_per_minute": 30},
                "evidence_class": "trial_uat" if provider == "adzuna" else "simulated_uat",
                "empirical_use_permitted": True if provider == "adzuna" else None,
                "trial_label": "ADZUNA_TRIAL_NOT_EMPIRICAL" if provider == "adzuna" else None,
                "permission": ADZUNA_PERMISSION if provider == "adzuna" else None,
                "attribution_note": ADZUNA_ATTRIBUTION_NOTE if provider == "adzuna" else None,
            },
        }
        source = ingestion_job_service.get_or_create_source(
            db=db,
            source_key=source_key,
            defaults=defaults,
        )
        if provider == "adzuna":
            apply_adzuna_permission(source)
            db.add(source)
        return source

    def ingest_payloads(
        self,
        db: Session,
        provider: str,
        payloads: List[Dict[str, Any]],
        actor_id: Optional[str],
        tenant_id: Optional[str] = None,
        source_label: Optional[str] = None,
        acquisition_mode: str = "simulated_uat",
    ) -> Dict[str, Any]:
        profile = self.provider_profile(provider)
        source = self.ensure_source(db, provider, tenant_id)
        permission = ADZUNA_PERMISSION if provider == "adzuna" else {}
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type=f"{provider}_job_board_payload_ingestion",
            triggered_by=actor_id,
            parameters={
                "simulated": acquisition_mode == "simulated_uat",
                "acquisition_mode": acquisition_mode,
                "records": len(payloads),
                "provider": provider,
                "empirical_use_permitted": (
                    permission.get("empirical_use_permitted")
                    if permission
                    else (False if acquisition_mode == "live_trial_uat" else None)
                ),
                **({
                    "permission_status": permission["permission_status"],
                    "permission_received_at": permission["permission_received_at"],
                    "permission_scope": permission["permission_scope"],
                    "attribution_required": permission["attribution_required"],
                    "attribution_url": permission["attribution_url"],
                    "attribution_note": ADZUNA_ATTRIBUTION_NOTE,
                } if permission else {}),
            },
        )
        ingestion_job_service.mark_running(db, job, total=len(payloads))

        inserted = 0
        updated = 0
        failed = 0
        for index, payload in enumerate(payloads, start=1):
            try:
                row = self.to_job_advert_row(profile, payload)
                normalised = job_advert_file_connector.normalise_row(
                    row=row,
                    source_label=source_label or provider,
                    default_region="South Africa",
                    default_country="ZA",
                    source_file=f"{provider}_api_payload.json",
                    row_index=index,
                )
                normalised["source_id"] = source.source_id
                normalised["ingestion_job_id"] = job.job_id
                result = job_advert_file_connector.upsert_job_posting(db, normalised)
                if result == "inserted":
                    inserted += 1
                else:
                    updated += 1
                ingestion_job_service.add_raw_record(
                    db=db,
                    job=job,
                    record_type=profile["record_type"],
                    raw_payload=_json_safe(payload),
                    source_record_id=str(row.get("job_id") or stable_hash(json.dumps(payload, sort_keys=True))[:24]),
                    content_hash=hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
                    validation_status="valid",
                    normalised_payload=_json_safe(normalised),
                )
                ingestion_job_service.update_progress(db, job, current=index, loaded_delta=1, seen_delta=1)
            except Exception as exc:
                failed += 1
                ingestion_job_service.update_progress(db, job, current=index, failed_delta=1, seen_delta=1)
                ingestion_job_service.add_raw_record(
                    db=db,
                    job=job,
                    record_type=profile["record_type"],
                    raw_payload=_json_safe(payload),
                    source_record_id=stable_hash(json.dumps(payload, sort_keys=True, default=str))[:24],
                    validation_status="failed",
                    normalised_payload={"error": str(exc), "provider": provider},
                )

        ingestion_job_service.mark_completed(db, job, status="completed_with_errors" if failed else "completed")
        return {
            "job_id": str(job.job_id),
            "source_id": str(source.source_id),
            "provider": provider,
            "records_seen": len(payloads),
            "inserted": inserted,
            "updated": updated,
            "failed": failed,
        }

    def to_job_advert_row(self, profile: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        field_map = profile["field_map"]
        row: Dict[str, Any] = {}
        for canonical, aliases in field_map.items():
            value = _first(payload, aliases)
            if canonical == "skills" and isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            row[canonical] = value
        job_id_prefix = profile.get("job_id_prefix")
        if job_id_prefix:
            row["job_id"] = f"{job_id_prefix}{row.get('job_id')}"
        if profile.get("structured_location_fields"):
            location = payload.get("location") or {}
            company = payload.get("company") or {}
            category = payload.get("category") or {}
            row["region"] = location.get("display_name") if isinstance(location, dict) else str(location)
            row["company"] = company.get("display_name") if isinstance(company, dict) else str(company)
            # A job-board category is not a declared skill.
            row["skills"] = None
        return row

    def fetch_pages(self, source: DataSource, auth_config: Dict[str, Any], max_pages: int = 1) -> List[Dict[str, Any]]:
        if not source.base_url:
            raise ValueError("Source has no base_url configured")
        config = source.config or {}
        pagination = config.get("pagination", {})
        rate_limit = config.get("rate_limit", {})
        params = dict(config.get("request_params", {}))
        headers = dict(config.get("headers", {}))
        if auth_config.get("api_key"):
            header_name = auth_config.get("api_key_header", "Authorization")
            prefix = auth_config.get("api_key_prefix", "Bearer")
            headers[header_name] = f"{prefix} {auth_config['api_key']}".strip()

        records: List[Dict[str, Any]] = []
        next_url: Optional[str] = source.base_url
        delay = 60 / max(float(rate_limit.get("requests_per_minute", 30)), 1.0)
        for page in range(1, max_pages + 1):
            response = requests.get(next_url or source.base_url, params=params, headers=headers, timeout=30)
            if response.status_code == 429:
                raise RuntimeError("API rate limit reached")
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                records.extend(item for item in payload if isinstance(item, dict))
                break
            data_path = pagination.get("data_path") or "data"
            page_records = payload.get(data_path, payload.get("items", []))
            if isinstance(page_records, list):
                records.extend(item for item in page_records if isinstance(item, dict))
            next_url = payload.get(pagination.get("next_url_field", "next"))
            if not next_url:
                break
            time.sleep(delay)
        return records


job_board_api_connector = JobBoardAPIConnector()
