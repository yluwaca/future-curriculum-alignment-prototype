"""
Bounded, idempotent pagination for Adzuna historical ingestion.

Adzuna exposes a single "current search" endpoint. The page number lives in
the URL path (``/v1/api/jobs/{country}/search/{page}``) and the maximum page
size is 50. There is no server-side ``date_from``/``date_to`` parameter, so
recency filtering is applied client-side against each record's ``created``
field.

Behavioural guarantees provided here:

1. Every run is bounded. The caller supplies an explicit page range and the
   module clamps it to hard server limits. Pages are never requested
   automatically beyond the caller's range.
2. Ingestion is additive and idempotent. The provider-stable ad id is stored
   as ``job_id`` (``ADZUNA-TRIAL-<id>``), exactly matching records imported by
   the legacy single-page route, and existing rows are never overwritten.
   Duplicates are reported as ``duplicate``, never replaced.
3. A complete audit trail is kept: the ingestion job's ``parameters`` capture
   the full query spec plus the per-page outcome summary, and every page
   request fires a ``log_audit_event``.
4. Polite throttling: requests are paced to the configured request rate and
   failures are retried with backoff (HTTP 429 honours ``Retry-After``). A run
   aborts after three consecutive failed pages instead of hammering upstream.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from app.services.audit_service import log_audit_event
from app.services.ingestion.adzuna_governance import (
    ADZUNA_ATTRIBUTION_NOTE,
    ADZUNA_PERMISSION,
    apply_adzuna_permission,
)
from app.services.ingestion.job_advert_file_connector import job_advert_file_connector
from app.services.ingestion.job_board_api_connector import job_board_api_connector
from app.services.ingestion.job_service import ingestion_job_service
from app.services.structured_log import log_structured

logger = logging.getLogger(__name__)


ADZUNA_SOURCE_KEY = "adzuna_jobs_api_trial"
ADZUNA_TRIAL_SOURCE_LABEL = "ADZUNA_TRIAL_NOT_EMPIRICAL"
ADZUNA_ACQUISITION_MODE = "live_trial_uat"
ADZUNA_SEARCH_BASE_URL = "https://api.adzuna.com/v1/api/jobs/za/search/{page}"
ADZUNA_RECORD_TYPE = "adzuna_job_payload"
ADZUNA_JOB_PREFIX = "ADZUNA-TRIAL-"

SYNTHETIC_SOURCE_KEY = "synthetic_jobs_api"
SYNTHETIC_JOB_PREFIX = "SYNTHETIC-"
DEFAULT_PROVIDER = "adzuna"
PROVIDER_ENV = "FUTURE_PAGINATED_JOB_PROVIDER"
SYNTHETIC_BASE_URL_ENV = "FUTURE_SYNTHETIC_JOBS_BASE_URL"

PAGINATED_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "adzuna": {
        "provider": "adzuna",
        "name": "Adzuna Jobs API (academic research permission)",
        "source_key": ADZUNA_SOURCE_KEY,
        "record_type": ADZUNA_RECORD_TYPE,
        "job_prefix": ADZUNA_JOB_PREFIX,
        "requires_credentials": True,
        "credential_env": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
        "base_url_template": ADZUNA_SEARCH_BASE_URL,
        "base_url_env": None,
        "base_url_suffix": None,
        "connector_profile": "adzuna",
        "connector_key": "adzuna",
        "source_type": "api",
        "acquisition_mode": ADZUNA_ACQUISITION_MODE,
        "empirical_use_permitted": ADZUNA_PERMISSION["empirical_use_permitted"],
        "permission": ADZUNA_PERMISSION,
        "structured_location_fields": True,
        "source_label": ADZUNA_TRIAL_SOURCE_LABEL,
    },
    "synthetic": {
        "provider": "synthetic",
        "name": "Synthetic Job Board (automated test fixture)",
        "source_key": SYNTHETIC_SOURCE_KEY,
        "record_type": "synthetic_job_payload",
        "job_prefix": SYNTHETIC_JOB_PREFIX,
        "requires_credentials": False,
        "credential_env": (),
        "base_url_template": None,
        "base_url_env": SYNTHETIC_BASE_URL_ENV,
        "base_url_suffix": "/search/{page}",
        "connector_profile": "synthetic",
        "connector_key": "synthetic",
        "source_type": "api",
        "acquisition_mode": "simulated_uat",
        "empirical_use_permitted": None,
        "structured_location_fields": True,
        "source_label": "SYNTHETIC_JOB_BOARD",
    },
}


def _default_provider() -> str:
    return (os.environ.get(PROVIDER_ENV, "") or DEFAULT_PROVIDER).strip().lower()


def provider_spec(provider: Optional[str] = None) -> Dict[str, Any]:
    """Resolve a paginated job provider key to its configuration.

    ``provider`` is optional: when omitted (or not a provider key) the active
    provider is taken from ``FUTURE_PAGINATED_JOB_PROVIDER`` (default
    ``adzuna``), so the same import path can be run against the synthetic
    fixture purely through configuration.
    """
    key = (
        (provider or "").strip().lower()
        if isinstance(provider, str) and str(provider).strip()
        else _default_provider()
    )
    spec = PAGINATED_PROVIDERS.get(key)
    if not spec:
        raise AdzunaPaginationError(f"Unsupported paginated job provider: {key}", status_code=422)
    return spec


def _provider_base_url_template(spec: Dict[str, Any]) -> str:
    """Build the ``{page}``-templated URL for a provider's search endpoint."""
    template = spec.get("base_url_template")
    if template:
        return template
    env_var = spec.get("base_url_env")
    base = os.environ.get(env_var, "") if env_var else ""
    if not base:
        raise AdzunaPaginationError(
            f"Provider '{spec['provider']}' base URL is not configured (set {env_var}).",
            status_code=503,
        )
    return base.rstrip("/") + (spec.get("base_url_suffix") or "/search/{page}")

PAGE_SIZE_MAX = 50
PAGE_NUMBER_MAX = 250
MAX_PAGES_PER_RUN = 250
DEFAULT_PAGE_RANGE = 10
MAX_RETRIES_PER_PAGE = 2
RATE_LIMIT_RETRY_SECONDS = (5, 10, 20)
BACKOFF_SECONDS = (2, 5, 10)
CONSECUTIVE_FAILURE_ABORT = 3
DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_SORT_BY = "date"
DEFAULT_SORT_DIRECTION = "down"
SAFE_BATCH_PAGES = 10
REQUEST_TIMEOUT_SECONDS = 30

ALLOWED_SORT_BY = {"date", "relevance", "salary", "default", "hybrid"}
ALLOWED_SORT_DIRECTION = {"up", "down"}


class AdzunaPaginationError(RuntimeError):
    """Raised for fatal config/runtime failures that map onto an HTTP status."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _json_safe(value: Any) -> Any:
    """Return a JSON-friendly deep copy, normalising special types to strings."""
    return json.loads(json.dumps(value, default=str))


def _content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class AdzunaPaginatedImporter:
    """Runs bounded, additive page imports against the Adzuna search API."""

    def __init__(self) -> None:
        import time

        self.sleep = time.sleep
        self.request_timeout_seconds = REQUEST_TIMEOUT_SECONDS

    # ------------------------------------------------------------------ spec
    def compute_spec(self, payload: Any) -> Dict[str, Any]:
        """Clamp the caller's request into the effective, server-bounded spec.

        Pure mathematics: never touches the network, safe to call for the
        estimate endpoint.
        """
        page_start = max(1, min(int(payload.page_start), PAGE_NUMBER_MAX))
        if payload.page_end is None:
            page_end = page_start + DEFAULT_PAGE_RANGE - 1
        else:
            page_end = max(page_start, int(payload.page_end))
        page_end = min(page_end, PAGE_NUMBER_MAX)
        page_end = min(page_end, page_start + MAX_PAGES_PER_RUN - 1)

        page_size = max(1, min(int(payload.page_size), PAGE_SIZE_MAX))
        sort_by = payload.sort_by if payload.sort_by in ALLOWED_SORT_BY else DEFAULT_SORT_BY
        sort_direction = (
            payload.sort_direction if payload.sort_direction in ALLOWED_SORT_DIRECTION else DEFAULT_SORT_DIRECTION
        )
        rpm = max(1, int(getattr(payload, "requests_per_minute", 0) or DEFAULT_REQUESTS_PER_MINUTE))

        return {
            "what": payload.what or None,
            "where": payload.where or None,
            "page_start": page_start,
            "page_end": page_end,
            "pages": (page_end - page_start) + 1,
            "page_size": page_size,
            "date_from": payload.date_from,
            "date_to": payload.date_to,
            "sort_by": sort_by,
            "sort_direction": sort_direction,
            "rate_limit": {
                "requests_per_minute": rpm,
                "delay_between_requests_seconds": round(60.0 / rpm, 2),
            },
            "server_page_cap": PAGE_NUMBER_MAX,
            "max_pages_per_run": MAX_PAGES_PER_RUN,
        }

    def estimate(self, payload: Any) -> Dict[str, Any]:
        """Preview a run without issuing a single API request."""
        spec = self.compute_spec(payload)
        pages = spec["pages"]
        rpm = spec["rate_limit"]["requests_per_minute"]
        wall_time = max(0, pages - 1) * (60.0 / rpm)
        return {
            **spec,
            "max_records_upper_bound": pages * spec["page_size"],
            "requests": pages,
            "wall_time_estimate_seconds": round(wall_time, 1),
            "safe_batch": pages <= SAFE_BATCH_PAGES,
        }

    # ----------------------------------------------------------- credentials
    def resolve_credentials(
        self,
        db: Session,
        credentials: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        spec = provider_spec(provider)
        if not spec["requires_credentials"]:
            return None, None
        app_id = (credentials or {}).get("app_id")
        app_key = (credentials or {}).get("api_key") or (credentials or {}).get("app_key")
        id_env, key_env = spec["credential_env"]
        app_id = app_id or os.environ.get(id_env)
        app_key = app_key or os.environ.get(key_env)
        if not app_id or not app_key:
            raise AdzunaPaginationError(
                f"{spec['name']} credentials are not configured on the server.", status_code=503
            )
        return str(app_id), str(app_key)

    # ------------------------------------------------------------ fetch loop
    def _parse_retry_after(self, value: Any) -> Optional[float]:
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _fetch_with_retry(self, url: str, params: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """GET a page with bounded retries, backoff and 429/Retry-After handling.

        Returns ``(payload, error)``. ``error`` is populated when the page
        ultimately failed; ``payload`` is only set on a well-formed 200.
        """
        last_error: Optional[str] = None
        for attempt in range(1 + MAX_RETRIES_PER_PAGE):
            try:
                response = requests.get(url, params=params, timeout=self.request_timeout_seconds)
            except requests.RequestException as exc:
                last_error = f"request exception: {exc}"
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            if response.status_code == 429:
                last_error = "HTTP 429 rate limit"
                delay = self._parse_retry_after(response.headers.get("Retry-After"))
                if not delay:
                    delay = RATE_LIMIT_RETRY_SECONDS[min(attempt, len(RATE_LIMIT_RETRY_SECONDS) - 1)]
                self.sleep(delay)
                continue
            if response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                return None, last_error
            try:
                body = response.json()
            except ValueError:
                last_error = "unexpected response format"
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            if not isinstance(body, dict):
                last_error = "unexpected response format"
                self.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
                continue
            return body, None
        return None, last_error or "request failed"

    # ------------------------------------------------------------ filtering
    @staticmethod
    def _parse_created(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return None

    def _date_filter_bound(self, value: Optional[str], at: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            d = date.fromisoformat(value)
        except ValueError:
            return None
        if at == "start":
            return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
        return datetime.combine(d, datetime.max.time()).replace(tzinfo=timezone.utc)

    def _filter_by_dates(self, payload: Dict[str, Any], lower: Optional[datetime], upper: Optional[datetime]) -> bool:
        """Client-side recency filter (Adzuna exposes no date_from/date_to)."""
        if lower is None and upper is None:
            return True
        created = self._parse_created(payload.get("created"))
        if not created:
            return False
        if lower and created < lower:
            return False
        if upper and created > upper:
            return False
        return True

    # --------------------------------------------------------- page handling
    def _add_raw_record(
        self,
        db: Session,
        job: Any,
        raw_payload: Dict[str, Any],
        job_id: Optional[str],
        validation_status: str,
        normalised: Optional[Dict[str, Any]] = None,
        record_type: str = ADZUNA_RECORD_TYPE,
    ) -> None:
        ingestion_job_service.add_raw_record(
            db=db,
            job=job,
            record_type=record_type,
            raw_payload=_json_safe(raw_payload),
            source_record_id=job_id or _content_hash(raw_payload)[:24],
            content_hash=_content_hash(raw_payload),
            validation_status=validation_status,
            normalised_payload=normalised and _json_safe(normalised),
        )

    def _process_page(
        self,
        db: Session,
        job: Any,
        source: Any,
        page: int,
        params_factory: Any,
        date_from: Optional[str],
        date_to: Optional[str],
        source_label: str,
        spec: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        spec = spec or PAGINATED_PROVIDERS[DEFAULT_PROVIDER]
        provider_key = spec["provider"]
        url = _provider_base_url_template(spec).format(page=page)
        body, error = self._fetch_with_retry(url, params_factory(page))
        outcome: Dict[str, Any] = {
            "page": page,
            "url": url,
            "status": "error" if error else "unknown",
            "error": error,
        }
        if body is None:
            return outcome

        results = body.get("results")
        if not isinstance(results, list):
            outcome["status"] = "error"
            outcome["error"] = "unexpected response format"
            return outcome

        if not results:
            outcome["status"] = "empty"
            outcome["records_returned"] = 0
            outcome["count_total"] = body.get("count")
            return outcome

        lower = self._date_filter_bound(date_from, "start")
        upper = self._date_filter_bound(date_to, "end")

        inserted = 0
        duplicate = 0
        date_skipped = 0
        failed = 0
        for raw in results:
            if not isinstance(raw, dict):
                failed += 1
                continue
            if not self._filter_by_dates(raw, lower, upper):
                date_skipped += 1
                continue
            try:
                row = job_board_api_connector.to_job_advert_row(
                    profile=job_board_api_connector.provider_profile(spec["connector_profile"]),
                    payload=raw,
                )
                normalised = job_advert_file_connector.normalise_row(
                    row=row,
                    source_label=source_label,
                    default_region="South Africa",
                    default_country="ZA",
                    source_file=f"{provider_key}_page_{page}.json",
                    row_index=page,
                )
            except Exception as exc:
                failed += 1
                self._add_raw_record(
                    db, job, raw, None, "failed", {"error": str(exc), "page": page}, record_type=spec["record_type"]
                )
                continue

            job_id_key = normalised.get("job_id")
            normalised["source_id"] = source.source_id
            normalised["ingestion_job_id"] = job.job_id
            normalised["metadata"] = dict(normalised.get("metadata") or {})
            normalised["metadata"]["page"] = page
            if provider_key == "adzuna":
                normalised["metadata"]["adzuna_page"] = page
            normalised["metadata"]["provider"] = provider_key

            if not job_id_key:
                failed += 1
                self._add_raw_record(
                    db, job, raw, None, "failed", normalised, record_type=spec["record_type"]
                )
                continue
            if not normalised.get("job_title"):
                failed += 1
                self._add_raw_record(
                    db, job, raw, job_id_key, "failed", normalised, record_type=spec["record_type"]
                )
                continue

            try:
                result = job_advert_file_connector.insert_job_posting_if_absent(db, normalised)
            except Exception as exc:
                failed += 1
                self._add_raw_record(
                    db, job, raw, job_id_key, "failed", {"error": str(exc), "page": page},
                    record_type=spec["record_type"],
                )
                continue

            if result == "inserted":
                inserted += 1
                validation_status = "valid"
            else:
                duplicate += 1
                validation_status = "duplicate"
            self._add_raw_record(
                db, job, raw, job_id_key, validation_status, normalised, record_type=spec["record_type"]
            )

        outcome.update(
            {
                "status": "success",
                "records_returned": len(results),
                "inserted": inserted,
                "duplicate": duplicate,
                "date_skipped": date_skipped,
                "failed": failed,
                "count_total": body.get("count"),
            }
        )
        return outcome

    # ------------------------------------------------------------- main flow
    def import_pages(
        self,
        db: Session,
        payload: Any,
        actor_type: Optional[str] = "system",
        actor_id: Optional[str] = None,
        token_id: Optional[str] = None,
        source_label: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        spec = self.compute_spec(payload)
        provider_key = provider_spec(provider)["provider"]
        provider_config = PAGINATED_PROVIDERS[provider_key]
        source_label = source_label or provider_config.get("source_label") or ADZUNA_TRIAL_SOURCE_LABEL
        app_id, app_key = self.resolve_credentials(db, credentials, provider=provider_key)
        source = ingestion_job_service.get_or_create_source(
            db=db,
            source_key=provider_config["source_key"],
            defaults={
                "name": provider_config["name"],
                "source_type": provider_config["source_type"],
                "tenant_id": None,
                "retry_policy": {
                    "max_attempts": 3,
                    "initial_backoff_seconds": 300,
                    "rate_limit_rpm": spec["rate_limit"]["requests_per_minute"],
                },
                "connector_key": provider_config["connector_key"],
            },
        )
        if provider_key == "adzuna":
            apply_adzuna_permission(source)
            db.add(source)

        permission = provider_config.get("permission")
        if permission is None:
            permission = ADZUNA_PERMISSION if provider_key == "adzuna" else {}
        job = ingestion_job_service.create_job(
            db=db,
            source=source,
            job_type=f"{provider_key}_paginated_import",
            triggered_by=actor_id,
            parameters={
                "acquisition_mode": provider_config["acquisition_mode"],
                "empirical_use_permitted": provider_config.get(
                    "empirical_use_permitted", permission.get("empirical_use_permitted")
                ),
                **({
                    "permission_status": permission["permission_status"],
                    "permission_received_at": permission["permission_received_at"],
                    "permission_scope": permission["permission_scope"],
                    "attribution_required": permission["attribution_required"],
                    "attribution_url": permission["attribution_url"],
                    "attribution_note": ADZUNA_ATTRIBUTION_NOTE,
                } if permission else {}),
                "provider": provider_key,
                "initiated_via": "portal",
                "query": {
                    "what": spec["what"],
                    "where": spec["where"],
                    "page_start": spec["page_start"],
                    "page_end": spec["page_end"],
                    "page_size": spec["page_size"],
                    "date_from": spec["date_from"],
                    "date_to": spec["date_to"],
                    "sort_by": spec["sort_by"],
                    "sort_direction": spec["sort_direction"],
                },
            },
        )
        ingestion_job_service.mark_running(db, job, total=spec["pages"])

        def params_factory(page: int) -> Dict[str, Any]:
            params: Dict[str, Any] = {
                "results_per_page": spec["page_size"],
                "sort_by": spec["sort_by"],
                "sort_direction": spec["sort_direction"],
            }
            if app_id:
                params["app_id"] = app_id
            if app_key:
                params["app_key"] = app_key
            if spec["what"]:
                params["what"] = spec["what"]
            if spec["where"]:
                params["where"] = spec["where"]
            return params

        delay_between_requests = spec["rate_limit"]["delay_between_requests_seconds"]
        page_outcomes: List[Dict[str, Any]] = []
        consecutive_failures = 0
        stop_reason = "limit_reached"

        for index, page in enumerate(range(spec["page_start"], spec["page_end"] + 1), start=1):
            if index > 1:
                self.sleep(delay_between_requests)
            outcome = self._process_page(
                db=db,
                job=job,
                source=source,
                page=page,
                params_factory=params_factory,
                date_from=spec["date_from"],
                date_to=spec["date_to"],
                source_label=source_label,
                spec=provider_config,
            )
            page_outcomes.append(outcome)
            log_audit_event(
                db=db,
                event_layer="application",
                event_type=f"{provider_key}_import",
                actor_type=actor_type or "system",
                actor_id=actor_id,
                token_id=token_id,
                source_component=f"ingestion.{provider_key}",
                action=f"import_{provider_key}_page",
                result="success" if outcome["status"] != "error" else "error",
                metadata={"provider": provider_key, "page": page, "status": outcome["status"], "url": outcome["url"]},
            )

            if outcome["status"] == "empty":
                stop_reason = "empty_page"
                break
            if outcome["status"] == "error":
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAILURE_ABORT:
                    stop_reason = "aborted_after_consecutive_failures"
                    break
            else:
                consecutive_failures = 0

            ingestion_job_service.update_progress(db, job, current=index, seen_delta=outcome.get("records_returned", 0))

        pages_succeeded = sum(1 for o in page_outcomes if o["status"] == "success")
        pages_empty = sum(1 for o in page_outcomes if o["status"] == "empty")
        pages_failed = sum(1 for o in page_outcomes if o["status"] == "error")
        total_inserted = sum(o.get("inserted", 0) for o in page_outcomes)
        total_duplicate = sum(o.get("duplicate", 0) for o in page_outcomes)
        total_date_skipped = sum(o.get("date_skipped", 0) for o in page_outcomes)
        total_failed = sum(o.get("failed", 0) for o in page_outcomes)
        total_returned = sum(o.get("records_returned", 0) for o in page_outcomes)

        all_pages_failed = pages_succeeded == 0 and pages_empty == 0
        any_errors = pages_failed > 0 or total_failed > 0
        mark_status = "completed_with_errors" if any_errors and not all_pages_failed else "completed"

        summary = {
            "job_id": str(job.job_id),
            "source_id": str(source.source_id),
            "provider": provider_key,
            "source_label": source_label,
            "what": spec["what"],
            "where": spec["where"],
            "page_start": spec["page_start"],
            "page_end": spec["page_end"],
            "page_size": spec["page_size"],
            "date_from": spec["date_from"],
            "date_to": spec["date_to"],
            "sort_by": spec["sort_by"],
            "sort_direction": spec["sort_direction"],
            "pages_requested": spec["pages"],
            "pages_attempted": len(page_outcomes),
            "pages_succeeded": pages_succeeded,
            "pages_empty": pages_empty,
            "pages_failed": pages_failed,
            "records_returned": total_returned,
            "records_date_filtered": total_date_skipped,
            "inserted": total_inserted,
            "duplicate": total_duplicate,
            "failed": total_failed,
            "stop_reason": stop_reason,
            "server_page_cap": PAGE_NUMBER_MAX,
            "max_pages_per_run": MAX_PAGES_PER_RUN,
            "page_outcomes": page_outcomes,
            "count_total": page_outcomes[0].get("count_total") if page_outcomes else None,
        }
        job.parameters = {**(job.parameters or {}), "page_outcomes": page_outcomes, "summary": summary}

        if all_pages_failed:
            ingestion_job_service.mark_failed(
                db,
                job,
                error=f"{provider_config['name']} requests failed for all {pages_failed} attempted page(s) "
                f"(stop_reason={stop_reason}). Last page error: {(page_outcomes[-1].get('error') if page_outcomes else '')}",
                failure_stage="pagination",
                failure_category="unknown",
            )
            log_audit_event(
                db=db,
                event_layer="application",
                event_type=f"{provider_key}_import",
                actor_type=actor_type or "system",
                actor_id=actor_id,
                token_id=token_id,
                source_component=f"ingestion.{provider_key}",
                action=f"import_{provider_key}_pages",
                result="error",
                metadata={
                    "job_type": f"{provider_key}_paginated_import",
                    "pages_requested": summary["pages_requested"],
                    "pages_failed": pages_failed,
                    "stop_reason": stop_reason,
                },
            )
            db.commit()
            log_structured(
                logger,
                "import_job",
                action="import_job_failed",
                outcome="error",
                provider=provider_key,
                source_label=source_label,
                job_id=str(job.job_id),
                stop_reason=stop_reason,
                pages_requested=summary["pages_requested"],
                pages_attempted=summary["pages_attempted"],
                pages_failed=pages_failed,
            )
            raise AdzunaPaginationError(
                f"{provider_config['name']} could not be reached across all retries. "
                f"Last page error: {(page_outcomes[-1].get('error') if page_outcomes else '')}",
                status_code=502,
            )

        ingestion_job_service.mark_completed(db, job, status=mark_status)

        log_audit_event(
            db=db,
            event_layer="application",
            event_type=f"{provider_key}_import",
            actor_type=actor_type or "system",
            actor_id=actor_id,
            token_id=token_id,
            source_component=f"ingestion.{provider_key}",
            action=f"import_{provider_key}_pages",
            result="success" if mark_status == "completed" else mark_status,
            metadata={
                "job_type": f"{provider_key}_paginated_import",
                "pages_requested": summary["pages_requested"],
                "pages_succeeded": summary["pages_succeeded"],
                "inserted": summary["inserted"],
                "duplicate": summary["duplicate"],
                "date_filtered": summary["records_date_filtered"],
                "failed": summary["failed"],
                "stop_reason": summary["stop_reason"],
            },
        )
        db.commit()
        log_structured(
            logger,
            "import_job",
            action="import_job_completed",
            outcome=mark_status,
            provider=provider_key,
            source_label=source_label,
            job_id=str(job.job_id),
            source_id=str(source.source_id),
            pages_requested=summary["pages_requested"],
            pages_attempted=summary["pages_attempted"],
            pages_succeeded=summary["pages_succeeded"],
            pages_failed=summary["pages_failed"],
            pages_empty=summary["pages_empty"],
            records_returned=summary["records_returned"],
            inserted=summary["inserted"],
            duplicate=summary["duplicate"],
            failed=summary["failed"],
            stop_reason=summary["stop_reason"],
        )
        return summary


adzuna_paginated_importer = AdzunaPaginatedImporter()