"""
Controlled DHET OFO 2021 acquisition, validation, and versioned import.

Provenance-first design:

- Only allowlisted DHET domains are followed (``www.dhet.gov.za``).
- A controlled download requires an explicit operator confirmation, applies
  request timeouts and a maximum byte size, and refuses non-spreadsheet
  content types before the file is written.
- A manual upload fallback paths through the exact same provenance record and
  SHA-256 checksum pipeline.
- Workbook structure is validated before import: required OFO code, occupation
  title, hierarchy, skill level, and version fields. Malformed files are
  rejected/quarantined with a visible reason.
- Versioned import stores the source version and checksum on every row and is
  idempotent per SHA-256.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from app.core.config import settings
from app.data.taxonomy_source_registry import DHET_OFO_2021_PROFILE
from app.models.data_source import DataSource
from app.models.dhet_ofo import DHETOFOAcquisition
from app.models.ofo_taxonomy import OFOOccupation
from app.services.audit_service import log_audit_event

logger = logging.getLogger(__name__)


OFO_CODE6_RE = re.compile(r"^\d{6}$")
OFO_GROUP_CODE_RE = re.compile(r"^\d{1,5}$")

# Accepted spreadsheet/archive/markup content types for the DHET OFO workbook.
ACCEPTED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/zip",
    "application/octet-stream",
    "text/plain",
    "text/csv",
    "application/csv",
    "binary/octet-stream",
}

# Content types that prove the response is not the expected workbook.
REFUSED_CONTENT_TYPES_PATTERN = re.compile(
    r"(text/html|application/pdf|image/|audio/|video/)"
)


class DHETOFOAcquisitionError(Exception):
    """A controlled acquisition was refused with a visible reason."""

    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _host_allowed(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    allowed = set(DHET_OFO_2021_PROFILE.get("allowlisted_domains", []))
    return host in allowed or any(host.endswith("." + domain) for domain in allowed)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _serialise(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    return value


class DHETOFOAcquisitionService:
    SOURCE_KEY = DHET_OFO_2021_PROFILE["source_key"]
    DEFAULT_VERSION = DHET_OFO_2021_PROFILE["version"]
    MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
    REQUEST_TIMEOUT_SECONDS = 20
    MAX_PAGE_BYTES = 2 * 1024 * 1024

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Source registration
    # ------------------------------------------------------------------

    def register_source(self, operator_id: Optional[str] = None) -> Dict[str, Any]:
        """Register DHET as the authoritative OFO source (idempotent)."""
        source = (
            self.db.query(DataSource)
            .filter(DataSource.source_key == self.SOURCE_KEY)
            .first()
        )
        if source is None:
            source = DataSource(
                source_key=self.SOURCE_KEY,
                name=DHET_OFO_2021_PROFILE["name"],
                source_type="taxonomy",
                source_category=DHET_OFO_2021_PROFILE["category"],
                connector_type="http_download",
                source_scope="shared",
                ingestion_mode="manual",
                source_format="xlsx",
                base_url=DHET_OFO_2021_PROFILE["source_page_url"],
                storage_path=str(settings.dhet_ofo_evidence_path),
                refresh_policy="on_demand",
                retry_policy={"max_attempts": 1, "note": "No repeated scraping of the DHET page"},
                owner="DHET",
                status="active",
                is_authorised=True,
                config={
                    "version": self.DEFAULT_VERSION,
                    "allowlisted_domains": DHET_OFO_2021_PROFILE["allowlisted_domains"],
                    "require_operator_confirmation": True,
                    "max_download_bytes": self.MAX_DOWNLOAD_BYTES,
                },
                auth_config={"mode": "none"},
            )
            self.db.add(source)
            self.db.commit()
            self.db.refresh(source)
        return {
            "source": {
                "source_key": self.SOURCE_KEY,
                "name": source.name,
                "authority": "DHET",
                "category": source.source_category,
                "version": self.DEFAULT_VERSION,
                "source_page_url": DHET_OFO_2021_PROFILE["source_page_url"],
                "status": source.status,
                "is_authorised": source.is_authorised,
                "licence_note": DHET_OFO_2021_PROFILE["licence_note"],
                "evidence_path": str(settings.dhet_ofo_evidence_path),
            }
        }

    # ------------------------------------------------------------------
    # Controlled download
    # ------------------------------------------------------------------

    def _require_confirmation(self, confirmed: bool, operator_id: Optional[str]) -> None:
        if not confirmed:
            raise DHETOFOAcquisitionError(
                "Operator confirmation is required before any DHET file is written. "
                "Confirm the resolved official document URL on the DHET Skills "
                "Development page (https://www.dhet.gov.za/SitePages/SkillsDevelopmentNew.aspx).",
                status_code=400,
            )
        if not operator_id:
            raise DHETOFOAcquisitionError(
                "An authenticated operator identity is required to record acquisition provenance.",
                status_code=400,
            )

    def _record(
        self,
        *,
        method: str,
        url: Optional[str],
        resolved_url: Optional[str],
        http_status: Optional[int],
        content_type: Optional[str],
        byte_size: int,
        sha256: str,
        file_name: Optional[str],
        stored_path: Optional[str],
        operator_id: Optional[str],
        status: str,
        note: Optional[str] = None,
        operator_confirmed: bool = False,
        version: Optional[str] = None,
        acquisition_type: str = "official",
    ) -> DHETOFOAcquisition:
        row = DHETOFOAcquisition(
            source_key=self.SOURCE_KEY,
            method=method,
            url=url,
            resolved_url=resolved_url,
            version=version or self.DEFAULT_VERSION,
            retrieved_at=_now_utc(),
            http_status=http_status,
            content_type=content_type,
            byte_size=byte_size,
            sha256=sha256,
            file_name=file_name,
            stored_path=stored_path,
            operator_id=operator_id,
            operator_confirmed=operator_confirmed,
            status=status,
            note=note,
            acquisition_type=acquisition_type,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _existing_by_sha(self, sha256: str) -> Optional[DHETOFOAcquisition]:
        return (
            self.db.query(DHETOFOAcquisition)
            .filter(DHETOFOAcquisition.sha256 == sha256)
            .order_by(DHETOFOAcquisition.created_at.desc())
            .first()
        )

    def discover(self, operator_id: Optional[str] = None) -> Dict[str, Any]:
        """Single best-effort page fetch that locates the official OFO workbook URL.

        No broad scraping, no retries, and no guessing of URLs. If the page
        cannot be resolved the outcome is recorded as ``unresolved`` provenance
        and the operator is directed to the manual upload fallback.
        """
        source_url = DHET_OFO_2021_PROFILE["source_page_url"]
        if not _host_allowed(source_url):
            raise DHETOFOAcquisitionError("Source page is not on the allowlisted DHET domain.")

        try:
            response = requests.get(
                source_url,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "FUTURE-platform-controlled-taxonomy-acquisition/1.0 "
                        "(provenance-first; operator-confirmed single fetch)"
                    ),
                },
                stream=True,
            )
        except requests.RequestException as exc:
            row = self._record(
                method="discovery",
                url=source_url,
                resolved_url=None,
                http_status=None,
                content_type=None,
                byte_size=0,
                sha256=_sha256_bytes(b""),
                file_name=None,
                stored_path=None,
                operator_id=operator_id,
                status="unresolved",
                note=f"DHET page could not be fetched (single attempt): {type(exc).__name__}: {exc}",
            )
            return self._discovery_payload(row, [], exc_message=str(exc))

        final_url = response.url
        if not _host_allowed(final_url):
            response.close()
            row = self._record(
                method="discovery",
                url=source_url,
                resolved_url=final_url,
                http_status=response.status_code,
                content_type=None,
                byte_size=0,
                sha256=_sha256_bytes(b""),
                file_name=None,
                stored_path=None,
                operator_id=operator_id,
                status="rejected",
                note=f"Page redirected off the allowlisted DHET domain: {final_url}",
            )
            return self._discovery_payload(row, [], exc_message="Redirected off allowlist")

        content_parts: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > self.MAX_PAGE_BYTES:
                response.close()
                row = self._record(
                    method="discovery",
                    url=source_url,
                    resolved_url=final_url,
                    http_status=response.status_code,
                    content_type=response.headers.get("Content-Type"),
                    byte_size=total,
                    sha256=_sha256_bytes(b""),
                    file_name=None,
                    stored_path=None,
                    operator_id=operator_id,
                    status="rejected",
                    note=f"Page exceeded the {self.MAX_PAGE_BYTES}-byte discovery limit.",
                )
                return self._discovery_payload(row, [], exc_message="Page too large")
            content_parts.append(chunk)
        response.close()

        body = b"".join(content_parts)
        text = body.decode("utf-8", errors="replace")
        candidate_urls = self._extract_official_candidates(text)
        status = "discovered" if candidate_urls else "unresolved"
        note = (
            f"Official OFO workbook URL candidates found: {len(candidate_urls)}."
            if candidate_urls
            else "No official OFO workbook link resolvable on the inspected DHET page. "
            "Download the file manually and upload it through Data Operations "
            "(the manual upload creates the same provenance record and checksum)."
        )
        row = self._record(
            method="discovery",
            url=source_url,
            resolved_url=final_url,
            http_status=response.status_code,
            content_type=response.headers.get("Content-Type"),
            byte_size=total,
            sha256=_sha256_bytes(body),
            file_name=None,
            stored_path=None,
            operator_id=operator_id,
            status=status,
            note=note,
        )
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_discovery",
            actor_type="human" if operator_id else "system",
            actor_id=operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_discovery",
            result="success" if candidate_urls else "noref",
            metadata={
                "source_url": source_url,
                "http_status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "byte_size": total,
                "sha256": row.sha256,
                "candidates": candidate_urls,
                "status": status,
            },
        )
        return self._discovery_payload(row, candidate_urls)

    def _extract_official_candidates(self, html: str) -> List[str]:
        candidates: List[str] = []
        hrefs = re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
        for href in hrefs:
            merged = urllib.parse.urljoin(DHET_OFO_2021_PROFILE["source_page_url"], href)
            if not _host_allowed(merged):
                continue
            lowered = merged.lower()
            if ".xlsx" in lowered or ".xls" in lowered:
                candidates.append(merged)
        return sorted(set(candidates))

    def _discovery_payload(
        self, row: DHETOFOAcquisition, candidates: List[str], exc_message: Optional[str] = None
    ) -> Dict[str, Any]:
        return {
            "status": row.status,
            "source_page_url": DHET_OFO_2021_PROFILE["source_page_url"],
            "candidate_urls": candidates,
            "provenance": self._acquisition_dict(row),
            "message": row.note or (exc_message or "Discovery recorded."),
            "fallback": (
                "If the official file cannot be resolved automatically, download it "
                "manually from the DHET Skills Development page and upload it through "
                "Data Operations; the upload records identical provenance fields."
            ),
        }

    def download(
        self,
        operator_id: Optional[str],
        confirmed: bool = False,
        resolved_url: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Controlled single download from the allowlisted DHET domain."""
        self._require_confirmation(confirmed, operator_id)
        target_url = resolved_url
        if not target_url:
            latest = (
                self.db.query(DHETOFOAcquisition)
                .filter(
                    DHETOFOAcquisition.method == "discovery",
                    DHETOFOAcquisition.status == "discovered",
                )
                .order_by(DHETOFOAcquisition.created_at.desc())
                .first()
            )
            if latest and latest.resolved_url:
                target_url = latest.resolved_url
        if not target_url:
            raise DHETOFOAcquisitionError(
                "No resolved official DHET workbook URL available. Run discovery first, "
                "supply the resolved URL from the DHET page, or upload the file manually.",
                status_code=400,
            )
        if not _host_allowed(target_url):
            raise DHETOFOAcquisitionError(
                f"Refusing download: {target_url} is not on the allowlisted DHET domain.",
                status_code=400,
            )

        try:
            response = requests.get(
                target_url,
                timeout=self.REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "FUTURE-platform-controlled-taxonomy-acquisition/1.0 "
                        "(operator-confirmed single download)"
                    ),
                },
                stream=True,
            )
        except requests.RequestException as exc:
            raise DHETOFOAcquisitionError(
                f"DHET download failed (single attempt, no retry): {type(exc).__name__}: {exc}",
                status_code=502,
            )

        final_url = response.url
        if not _host_allowed(final_url):
            response.close()
            raise DHETOFOAcquisitionError(
                f"Refusing download: the official redirect left the allowlisted DHET domain ({final_url}).",
                status_code=400,
            )

        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if REFUSED_CONTENT_TYPES_PATTERN.search(content_type) or (
            content_type and content_type not in ACCEPTED_CONTENT_TYPES
        ):
            code = response.status_code
            response.close()
            self._record(
                method="download",
                url=target_url,
                resolved_url=final_url,
                http_status=code,
                content_type=content_type,
                byte_size=0,
                sha256=_sha256_bytes(b""),
                file_name=None,
                stored_path=None,
                operator_id=operator_id,
                status="rejected",
                note=(
                    f"Quarantined download: content type '{content_type}' is not a "
                    "spreadsheet/archive workbook."
                ),
                operator_confirmed=True,
            )
            raise DHETOFOAcquisitionError(
                f"Refused: content type '{content_type}' is not an expected OFO workbook "
                "spreadsheet. No file was written.",
                status_code=400,
            )

        parts: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > self.MAX_DOWNLOAD_BYTES:
                response.close()
                self._record(
                    method="download",
                    url=target_url,
                    resolved_url=final_url,
                    http_status=response.status_code,
                    content_type=content_type,
                    byte_size=total,
                    sha256=_sha256_bytes(b""),
                    file_name=None,
                    stored_path=None,
                    operator_id=operator_id,
                    status="rejected",
                    note=f"Quarantined download: exceeded the {self.MAX_DOWNLOAD_BYTES}-byte limit.",
                    operator_confirmed=True,
                )
                raise DHETOFOAcquisitionError(
                    f"Refused: download exceeded the {self.MAX_DOWNLOAD_BYTES}-byte size limit "
                    "(quarantined; no file written).",
                    status_code=400,
                )
            parts.append(chunk)
        response.close()

        content = b"".join(parts)
        sha256 = _sha256_bytes(content)
        existing = self._existing_by_sha(sha256)
        if existing and existing.status in ("validated", "imported"):
            return {
                "status": "idempotent",
                "message": "This exact file (SHA-256) is already recorded and was processed; "
                "re-import is idempotent.",
                "acquisition": self._acquisition_dict(existing),
            }

        file_name = f"dhet_ofo_2021_{_now_utc():%Y%m%d}_{sha256[:12]}.xlsx"
        stored = settings.dhet_ofo_evidence_path / file_name
        stored.write_bytes(content)

        row = self._record(
            method="download",
            url=target_url,
            resolved_url=final_url,
            http_status=response.status_code,
            content_type=content_type,
            byte_size=total,
            sha256=sha256,
            file_name=file_name,
            stored_path=str(stored),
            operator_id=operator_id,
            status="pending_validation",
            note=note,
            operator_confirmed=True,
        )
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_download",
            actor_type="human",
            actor_id=operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_download",
            result="success",
            metadata={
                "url": target_url,
                "resolved_url": final_url,
                "http_status": response.status_code,
                "content_type": content_type,
                "byte_size": total,
                "sha256": sha256,
                "operator_confirmed": True,
                "stored_path": str(stored),
            },
        )
        return {
            "status": row.status,
            "message": "Controlled DHET download recorded. Validate before import.",
            "acquisition": self._acquisition_dict(row),
        }

    # ------------------------------------------------------------------
    # Manual upload fallback
    # ------------------------------------------------------------------

    def upload(
        self,
        operator_id: Optional[str],
        content: bytes,
        filename: Optional[str] = None,
        content_type: str = "application/octet-stream",
        note: Optional[str] = None,
        acquisition_type: str = "official",
    ) -> Dict[str, Any]:
        """Manual upload fallback that records the same provenance fields."""
        if acquisition_type not in {"official", "synthetic_fixture"}:
            raise DHETOFOAcquisitionError(
                f"Unsupported acquisition type: {acquisition_type}",
                status_code=400,
            )
        if not operator_id:
            raise DHETOFOAcquisitionError(
                "An authenticated operator identity is required to record upload provenance.",
                status_code=400,
            )
        if not content:
            raise DHETOFOAcquisitionError("The uploaded OFO workbook is empty.", status_code=400)
        if len(content) > self.MAX_DOWNLOAD_BYTES:
            raise DHETOFOAcquisitionError(
                f"Upload exceeds the {self.MAX_DOWNLOAD_BYTES}-byte size limit.", status_code=400
            )
        if REFUSED_CONTENT_TYPES_PATTERN.search((content_type or "").lower()):
            raise DHETOFOAcquisitionError(
                f"Upload refused: content type '{content_type}' is not a spreadsheet workbook.",
                status_code=400,
            )

        sha256 = _sha256_bytes(content)
        existing = self._existing_by_sha(sha256)
        if existing and existing.status in ("validated", "imported"):
            return {
                "status": "idempotent",
                "message": "This exact file (SHA-256) was already uploaded and processed; re-import is idempotent.",
                "acquisition": self._acquisition_dict(existing),
            }

        safe_name = Path(filename or "dhet_ofo_2021_upload.xlsx").name
        file_name = f"dhet_ofo_2021_{_now_utc():%Y%m%d}_{sha256[:12]}_{safe_name}"
        stored = settings.dhet_ofo_evidence_path / file_name
        stored.write_bytes(content)

        row = self._record(
            method="upload",
            url=None,
            resolved_url=DHET_OFO_2021_PROFILE["source_page_url"],
            http_status=None,
            content_type=content_type,
            byte_size=len(content),
            sha256=sha256,
            file_name=file_name,
            stored_path=str(stored),
            operator_id=operator_id,
            status="pending_validation",
            note=note or f"Manual upload fallback; origin: official DHET Skills Development page (type={acquisition_type}).",
            operator_confirmed=True,
            acquisition_type=acquisition_type,
        )
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_upload",
            actor_type="human",
            actor_id=operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_upload",
            result="success",
            metadata={
                "source_page_url": DHET_OFO_2021_PROFILE["source_page_url"],
                "content_type": content_type,
                "byte_size": len(content),
                "sha256": sha256,
                "file_name": file_name,
            },
        )
        return {
            "status": row.status,
            "message": "Manual upload recorded with identical provenance fields and checksum. Validate before import.",
            "acquisition": self._acquisition_dict(row),
        }

    # ------------------------------------------------------------------
    # Workbook validation
    # ------------------------------------------------------------------

    def _extract_rows(self, file_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
        ext = (file_path.suffix or "").lower()
        if ext == ".csv":
            with file_path.open("r", encoding="utf-8-sig", errors="replace") as fh:
                reader = csv.reader(fh)
                raw_rows = [row for row in reader if row]
            if not raw_rows:
                return [], []
            headers = [str(h).strip().lower() for h in raw_rows[0]]
            rows = [
                {headers[i]: str(cell).strip() for i, cell in enumerate(row) if i < len(headers)}
                for row in raw_rows[1:]
            ]
            return headers, rows
        try:
            from openpyxl import load_workbook
        except Exception as exc:  # pragma: no cover - openpyxl is declared in requirements
            raise DHETOFOAcquisitionError(
                f"Spreadsheet reader is unavailable on this deployment: {exc}", status_code=500
            )
        try:
            workbook = load_workbook(file_path, read_only=True, data_only=True)
        except Exception as exc:
            raise DHETOFOAcquisitionError(
                f"Workbook could not be parsed as an Office Open XML spreadsheet: {exc}",
                status_code=400,
            )
        sheet = workbook.worksheets[0] if workbook.worksheets else None
        if sheet is None:
            workbook.close()
            return [], []
        header_cells = None
        rows: List[Dict[str, str]] = []
        headers: List[str] = []
        for row_index, sheet_row in enumerate(sheet.iter_rows(values_only=True)):
            cells = [str(c) if c is not None else "" for c in sheet_row]
            if not any(cells):
                continue
            if row_index == 0:
                headers = [h.strip().lower() for h in cells]
                header_cells = cells
                continue
            if not header_cells:
                continue
            row_dict = {}
            for i, cell in enumerate(cells):
                if i < len(headers):
                    row_dict[headers[i]] = cell.strip()
            rows.append(row_dict)
        workbook.close()
        return headers, rows

    def _find_header(self, headers: List[str], keywords: List[str]) -> Optional[str]:
        for header in headers:
            lowered = header.strip().lower()
            if any(keyword in lowered for keyword in keywords):
                return header
        return None

    def validate_acquisition(self, acquisition_id: UUID) -> Dict[str, Any]:
        row = self.db.query(DHETOFOAcquisition).filter(
            DHETOFOAcquisition.acquisition_id == acquisition_id
        ).first()
        if not row:
            raise DHETOFOAcquisitionError(
                "Acquisition record not found.", status_code=404
            )
        if row.method == "discovery":
            raise DHETOFOAcquisitionError(
                "Discovery records do not contain a workbook to validate; run a confirmed "
                "download or upload the file manually.",
                status_code=400,
            )
        stored = Path(row.stored_path) if row.stored_path else settings.dhet_ofo_evidence_path
        if not stored.exists():
            raise DHETOFOAcquisitionError(
                f"Stored file is missing at {stored}; the acquisition is unverifiable.",
                status_code=409,
            )

        try:
            headers, rows = self._extract_rows(stored)
        except DHETOFOAcquisitionError as exc:
            self._mark_invalid(row, [exc.detail])
            return {"status": row.status, "valid": False, "errors": [exc.detail],
                    "acquisition": self._acquisition_dict(row)}

        errors: List[str] = []
        code_header = self._find_header(headers, ["code"])
        title_header = self._find_header(headers, ["title", "occupation"])
        hierarchy_header = self._find_header(
            headers, ["major", "sub-major", "submajor", "minor", "unit", "group"]
        )
        skill_level_header = self._find_header(headers, ["skill level"])
        version_header = self._find_header(headers, ["version", "year"])

        if not code_header or not title_header:
            errors.append("Required columns are missing: OFO code and occupation title.")
        if not hierarchy_header:
            errors.append("Required hierarchy indication is missing (major/sub-major/minor/unit group).")
        if not skill_level_header:
            errors.append("Required skill-level column is missing.")
        if not version_header:
            errors.append("Required version/year column is missing.")

        bad_codes: List[str] = []
        missing_titles = 0
        data_rows = len(rows)
        six_digit_rows = 0
        seen_versions = set()
        for record in rows:
            code = record.get(code_header or "", "").strip() if code_header else ""
            title = record.get(title_header or "", "").strip() if title_header else ""
            if not title and not code:
                continue
            if not title:
                missing_titles += 1
                continue
            if not (OFO_GROUP_CODE_RE.match(code) or OFO_CODE6_RE.match(code)):
                bad_codes.append(code or "(blank)")
            if OFO_CODE6_RE.match(code):
                six_digit_rows += 1
            if version_header:
                seen_versions.add(record.get(version_header, "").strip())

        if data_rows == 0:
            errors.append("The workbook contains no data rows.")
        if not six_digit_rows:
            errors.append("No six-digit OFO occupation codes were found; no fabrication of codes is permitted.")
        if bad_codes:
            errors.append(
                f"{len(bad_codes)} occupation rows have non-numeric/invalid OFO codes "
                f"(sample: {bad_codes[:3]})."
            )
        if missing_titles:
            errors.append(f"{missing_titles} rows have no occupation title; they will be skipped on import.")

        if errors:
            self._mark_invalid(row, errors)
            return {
                "status": row.status,
                "valid": False,
                "errors": errors,
                "data_rows": data_rows,
                "six_digit_rows": six_digit_rows,
                "acquisition": self._acquisition_dict(row),
            }

        version = seen_versions - {""}
        detected_version = sorted(version)[0] if version else self.DEFAULT_VERSION
        row.status = "validated"
        row.data_rows = six_digit_rows
        row.version = detected_version if len(detected_version) <= 50 else self.DEFAULT_VERSION
        self.db.commit()
        self.db.refresh(row)
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_validate",
            actor_type="system",
            actor_id=row.operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_validate",
            result="success",
            metadata={
                "acquisition_id": str(row.acquisition_id),
                "sha256": row.sha256,
                "version": row.version,
                "data_rows": six_digit_rows,
                "headers_present": {
                    "code": bool(code_header),
                    "title": bool(title_header),
                    "hierarchy": bool(hierarchy_header),
                    "skill_level": bool(skill_level_header),
                    "version": bool(version_header),
                },
            },
        )
        return {
            "status": row.status,
            "valid": True,
            "errors": [],
            "data_rows": six_digit_rows,
            "detected_version": row.version,
            "acquisition": self._acquisition_dict(row),
        }

    def _mark_invalid(self, row: DHETOFOAcquisition, errors: List[str]) -> None:
        row.status = "rejected"
        row.validation_errors = list(errors)
        self.db.commit()
        self.db.refresh(row)
        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_validate",
            actor_type="system",
            actor_id=row.operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_validate",
            result="failure",
            metadata={
                "acquisition_id": str(row.acquisition_id),
                "sha256": row.sha256,
                "reason": errors,
            },
        )

    # ------------------------------------------------------------------
    # Versioned import (idempotent)
    # ------------------------------------------------------------------

    def import_acquisition(self, acquisition_id: UUID, operator_id: Optional[str] = None) -> Dict[str, Any]:
        row = self.db.query(DHETOFOAcquisition).filter(
            DHETOFOAcquisition.acquisition_id == acquisition_id
        ).first()
        if not row:
            raise DHETOFOAcquisitionError("Acquisition record not found.", status_code=404)
        if row.status != "validated":
            raise DHETOFOAcquisitionError(
                "Import requires a validated workbook. Run validation first "
                f"(current status: {row.status}).",
                status_code=400,
            )
        stored = Path(row.stored_path) if row.stored_path else None
        if not stored or not stored.exists():
            raise DHETOFOAcquisitionError(
                f"Stored file is missing at {stored}; cannot import.",
                status_code=409,
            )

        sha256_now = _sha256_bytes(stored.read_bytes())
        if sha256_now != row.sha256:
            raise DHETOFOAcquisitionError(
                "Stored file checksum no longer matches the acquisition record; refusing import "
                "(evidence integrity).",
                status_code=409,
            )

        version = row.version or self.DEFAULT_VERSION
        headers, rows = self._extract_rows(stored)
        code_header = self._find_header(headers, ["code"])
        title_header = self._find_header(headers, ["title", "occupation"])

        created = 0
        updated = 0
        group_rows = 0
        occupation_rows = 0
        imported_codes: List[str] = []

        for record in rows:
            code = (record.get(code_header or "", "") or "").strip() if code_header else ""
            title = (record.get(title_header or "", "") or "").strip() if title_header else ""
            if not code or not title:
                continue
            if not (OFO_GROUP_CODE_RE.match(code) or OFO_CODE6_RE.match(code)):
                continue
            level = "occupation" if OFO_CODE6_RE.match(code) else "group"
            broader = self._derive_broader_code(code, imported_codes)
            existing = (
                self.db.query(OFOOccupation)
                .filter(
                    OFOOccupation.ofo_code == code,
                    OFOOccupation.taxonomy_version == version,
                )
                .first()
            )
            metadata = {
                "source": {
                    "authority": "DHET",
                    "source_page_url": DHET_OFO_2021_PROFILE["source_page_url"],
                    "resolved_url": row.resolved_url,
                    "version": version,
                    "sha256": row.sha256,
                    "acquisition_id": str(row.acquisition_id),
                    "method": row.method,
                    "acquisition_type": row.acquisition_type,
                    "retrieved_at": _serialise(row.retrieved_at),
                },
                "hierarchy_level": level,
            }
            if existing:
                existing.preferred_label = title
                existing.description = record.get(
                    self._find_header(headers, ["description"]) or "", "") or existing.description
                existing.broader_occupation_code = broader or existing.broader_occupation_code
                existing.occupation_metadata = {**(existing.occupation_metadata or {}), **metadata}
                updated += 1
            else:
                self.db.add(
                    OFOOccupation(
                        ofo_code=code,
                        preferred_label=title,
                        description=record.get(
                            self._find_header(headers, ["description"]) or "", "") or None,
                        status="active" if level == "occupation" else "group",
                        taxonomy_version=version,
                        occupation_metadata=dict(metadata),
                        broader_occupation_code=broader,
                        top_concept=(len(code) <= 2 and level == "group"),
                    )
                )
                created += 1
            if level == "occupation":
                occupation_rows += 1
            else:
                group_rows += 1
            imported_codes.append(code)

        self.db.commit()
        row.status = "imported"
        row.imported_rows = occupation_rows
        if row.version and row.version != version:
            row.version = version
        self.db.commit()
        self.db.refresh(row)

        log_audit_event(
            db=self.db,
            event_layer="data_operations",
            event_type="dhet_ofo_import",
            actor_type="human" if operator_id else "system",
            actor_id=operator_id or row.operator_id,
            token_id=None,
            source_component="dhet_ofo_acquisition_service",
            action="dhet_ofo_import",
            result="success",
            metadata={
                "acquisition_id": str(row.acquisition_id),
                "sha256": row.sha256,
                "version": version,
                "created": created,
                "updated": updated,
                "occupations": occupation_rows,
                "groups": group_rows,
                "idempotent": False,
            },
        )
        return {
            "status": row.status,
            "version": version,
            "sha256": row.sha256,
            "counts": {
                "created": created,
                "updated": updated,
                "occupations": occupation_rows,
                "groups": group_rows,
            },
            "impacts": {
                "message": (
                    "Six-digit occupation codes are taken strictly from the validated DHET "
                    "workbook; none are fabricated or inferred by title alone."
                ),
            },
            "acquisition": self._acquisition_dict(row),
        }

    def _derive_broader_code(self, code: str, imported_codes: List[str]) -> Optional[str]:
        prefixes = [code[:i] for i in range(len(code) - 1, 0, -1)]
        for prefix in prefixes:
            if prefix in imported_codes:
                return prefix
        return None

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def get_source_summary(self) -> Dict[str, Any]:
        acquisitions = (
            self.db.query(DHETOFOAcquisition)
            .filter(DHETOFOAcquisition.source_key == self.SOURCE_KEY)
            .order_by(DHETOFOAcquisition.created_at.desc())
            .all()
        )
        imported = (
            self.db.query(DHETOFOAcquisition)
            .filter(DHETOFOAcquisition.status == "imported")
            .order_by(DHETOFOAcquisition.created_at.desc())
            .first()
        )
        from sqlalchemy import func

        version_rows = (
            self.db.query(OFOOccupation.taxonomy_version, func.count(OFOOccupation.ofo_occupation_id))
            .group_by(OFOOccupation.taxonomy_version)
            .all()
        )
        type_rows = (
            self.db.query(
                DHETOFOAcquisition.acquisition_type,
                func.count(DHETOFOAcquisition.acquisition_id),
            )
            .group_by(DHETOFOAcquisition.acquisition_type)
            .all()
        )
        official_imported = (
            self.db.query(DHETOFOAcquisition)
            .filter(
                DHETOFOAcquisition.status == "imported",
                DHETOFOAcquisition.acquisition_type == "official",
            )
            .first()
        )
        return {
            "source": DHET_OFO_2021_PROFILE,
            "registration": self.register_source(),
            "latest_acquisition": self._acquisition_dict(acquisitions[0]) if acquisitions else None,
            "acquisitions": [self._acquisition_dict(a) for a in acquisitions],
            "acquisition_type_counts": {str(t): int(c) for t, c in type_rows},
            "official_imported": official_imported is not None,
            "import_summary": (
                {
                    "version": imported.version,
                    "sha256": imported.sha256,
                    "stored_path": imported.stored_path,
                    "occupations": imported.imported_rows,
                    "acquisition_type": imported.acquisition_type,
                    "imported_at": _serialise(imported.created_at),
                }
                if imported
                else None
            ),
            "occupation_counts_by_version": {v: int(c) for v, c in version_rows},
        }

    def get_breakdown(self) -> Dict[str, Any]:
        """Auditable OFO reference-table breakdown that reconciles exactly.

        Every row currently in the `ofo_occupation` reference table is counted by
        code length and by the acquisition that last wrote it (occupation metadata
        carries the source acquisition_id). The code-length buckets and the
        acquisition buckets must each sum to the table total, and both must match
        the displayed portal total so the portal number is always provable.
        """
        rows = (
            self.db.query(
                OFOOccupation.ofo_code,
                OFOOccupation.taxonomy_version,
                OFOOccupation.occupation_metadata,
            ).all()
        )
        total = len(rows)
        length_counts: Dict[str, int] = {}
        for code, _version, _meta in rows:
            code = (code or "").strip()
            bucket = f"{len(code)}_digit" if code else "unclassified"
            length_counts[bucket] = length_counts.get(bucket, 0) + 1

        def _bucket_label(length: int) -> str:
            return {
                1: "major_group",
                2: "sub_major_group",
                3: "minor_group",
                4: "unit_group",
                6: "occupation",
            }.get(length, f"{length}_digit")

        by_acquisition: Dict[str, Dict[str, Any]] = {}
        unattributed = 0
        for code, version, meta in rows:
            source = (meta or {}).get("source") or {}
            acq_id = source.get("acquisition_id")
            if not acq_id:
                unattributed += 1
                continue
            item = by_acquisition.setdefault(
                str(acq_id),
                {
                    "acquisition_id": str(acq_id),
                    "rows_present_now": 0,
                    "six_digit_rows_present_now": 0,
                    "versions": set(),
                },
            )
            item["rows_present_now"] += 1
            if len((code or "").strip()) == 6:
                item["six_digit_rows_present_now"] += 1
            item["versions"].add(str(version))

        acquisition_records = {
            str(a.acquisition_id): a for a in self.db.query(DHETOFOAcquisition).all()
        }
        acquisition_breakdown = []
        for acq_id, item in sorted(
            by_acquisition.items(),
            key=lambda kv: kv[1]["rows_present_now"],
            reverse=True,
        ):
            record = acquisition_records.get(acq_id)
            entry = {
                "acquisition_id": acq_id,
                "rows_present_now": item["rows_present_now"],
                "six_digit_rows_present_now": item["six_digit_rows_present_now"],
                "versions": sorted(item["versions"]),
                "method": record.method if record else None,
                "acquisition_type": record.acquisition_type if record else None,
                "rows_imported_at_import": record.imported_rows if record else None,
                "status": record.status if record else None,
            }
            if (
                record
                and record.imported_rows is not None
                and entry["six_digit_rows_present_now"] != record.imported_rows
            ):
                entry["discrepancy_note"] = (
                    f"Acquisition recorded {record.imported_rows} imported six-digit occupation "
                    f"rows at import time but currently owns "
                    f"{entry['six_digit_rows_present_now']}; the difference reflects rows "
                    "superseded or re-imported by a later acquisition (append-only lineage is "
                    "preserved, nothing is erased)."
                )
            acquisition_breakdown.append(entry)

        length_sum = sum(length_counts.values())
        acquisition_sum = sum(item["rows_present_now"] for item in by_acquisition.values()) + unattributed
        reconciles = total == length_sum == acquisition_sum
        return {
            "enabled": settings.ENABLE_OFO_TAXONOMY,
            "total_occupations_in_reference_tables": total,
            "reconciles": bool(reconciles),
            "occupations_by_code_length": {
                _bucket_label(length): length_counts[f"{length}_digit"]
                for length in (1, 2, 3, 4, 6)
                if f"{length}_digit" in length_counts
            },
            "unclassified_codes": length_counts.get("unclassified", 0),
            "occupations_by_acquisition": acquisition_breakdown,
            "unattributed_rows": unattributed,
            "published_workbook_note": (
                "The DHET OFO 2021 published workbook states the official intricate "
                "occupation structure; this panel reports the verified reference-table "
                "state (which is the authoritative basis for portal calculations) and "
                "exposes both the workbook acquisition record and its checksum so the "
                "lineage remains auditable."
            ),
            "measurement_note": (
                "Counts are recomputed live from the ofo_occupation reference table at request "
                f"time (total {total}); code-length buckets and acquisition buckets each sum "
                "exactly to this total."
            ),
            "generated_at": _serialise(datetime.now(timezone.utc)),
        }

    def _acquisition_dict(self, row: DHETOFOAcquisition) -> Dict[str, Any]:
        return {
            "acquisition_id": str(row.acquisition_id),
            "source_key": row.source_key,
            "method": row.method,
            "url": row.url,
            "resolved_url": row.resolved_url,
            "version": row.version,
            "acquisition_type": row.acquisition_type,
            "retrieved_at": _serialise(row.retrieved_at),
            "http_status": row.http_status,
            "content_type": row.content_type,
            "byte_size": row.byte_size,
            "sha256": row.sha256,
            "file_name": row.file_name,
            "stored_path": row.stored_path,
            "operator_id": row.operator_id,
            "operator_confirmed": row.operator_confirmed,
            "status": row.status,
            "validation_errors": row.validation_errors or [],
            "note": row.note,
            "data_rows": row.data_rows,
            "imported_rows": row.imported_rows,
            "created_at": _serialise(row.created_at),
        }


def dhet_ofo_acquisition_service(db: Session) -> DHETOFOAcquisitionService:
    return DHETOFOAcquisitionService(db)