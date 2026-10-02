#!/usr/bin/env python3
"""Idempotent API smoke test using visibly synthetic demo records only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIXTURES = ROOT / "demo" / "fixtures"
DEFAULT_REPORT = ROOT / "demo" / "output" / "smoke-report.json"
API = "/api/v1"


class SmokeFailure(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, timeout: int = 45):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None

    def request(self, method: str, path: str, *, body: bytes | None = None,
                content_type: str | None = None, expected=(200,)):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw_preview": raw[:500].decode("utf-8", errors="replace")}
        if status not in expected:
            raise SmokeFailure(f"{method} {path} returned {status}: {payload}")
        return status, payload

    def json(self, method: str, path: str, payload=None, expected=(200,)):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        return self.request(method, path, body=body, content_type="application/json" if body else None,
                            expected=expected)

    def multipart(self, path: str, fields: dict[str, str], file_field: str, file_path: Path,
                  expected=(200, 201, 202)):
        boundary = "----PCLMASSmoke" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks += [f"--{boundary}\r\n".encode(),
                       f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                       str(value).encode(), b"\r\n"]
        mime = "text/csv" if file_path.suffix == ".csv" else "text/plain"
        chunks += [f"--{boundary}\r\n".encode(),
                   f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode(),
                   f"Content-Type: {mime}\r\n\r\n".encode(), file_path.read_bytes(), b"\r\n",
                   f"--{boundary}--\r\n".encode()]
        return self.request("POST", path, body=b"".join(chunks),
                            content_type=f"multipart/form-data; boundary={boundary}", expected=expected)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def redacted_summary(value):
    """Keep evidence useful while avoiding retained raw text or tokens."""
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(value.keys()),
                "count_fields": {k: v for k, v in value.items() if k.endswith("count") and isinstance(v, (int, float))}}
    return {"type": type(value).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("PCLMAS_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--wait-seconds", type=int, default=120)
    args = parser.parse_args()
    username = os.getenv("PCLMAS_SMOKE_USERNAME")
    password = os.getenv("PCLMAS_SMOKE_PASSWORD")
    if not username or not password:
        raise SmokeFailure("Set PCLMAS_SMOKE_USERNAME and PCLMAS_SMOKE_PASSWORD; credentials are never stored in the report.")

    manifest = json.loads((FIXTURES / "fixture_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("classification") != "synthetic_demo_only" or manifest.get("empirical_evidence") is not False:
        raise SmokeFailure("Fixture manifest must explicitly classify all records as non-empirical synthetic demo data")
    checksums = {name: digest(FIXTURES / name) for name in manifest["files"]}
    client = Client(args.base_url)
    stages: list[dict] = []

    def stage(name, method, path, **kwargs):
        status, payload = client.json(method, path, **kwargs)
        stages.append({"stage": name, "http_status": status, "response": redacted_summary(payload)})
        return payload

    stage("liveness", "GET", "/health")
    stage("readiness", "GET", "/ready")
    login = stage("authentication", "POST", API + "/auth/login",
                  payload={"identifier": username, "password": password})
    password = None
    client.token = login.get("access_token")
    if not client.token:
        raise SmokeFailure("Login response did not contain an access token")

    # Curriculum is queued by the real durable upload endpoint. document_key makes the fixture stable.
    documents = stage("curriculum_inventory_before", "GET", API + "/curriculum/documents")
    # The ingestion contract canonicalises document keys with its versioned slug rule.
    # Use that canonical representation for both submission and inventory matching.
    document_key = "synthetic-demo-curriculum-v1"
    existing = next((d for d in documents if d.get("document_key") == document_key), None)
    curriculum_action = "reused"
    if not existing:
        status, uploaded = client.multipart(
            API + "/curriculum/documents/upload",
            {"title": "SYNTHETIC DEMO — Applied ICT", "faculty": "Synthetic Demo Faculty",
             "department": "Synthetic Demo Department", "programme": "Synthetic Diploma in Applied ICT",
             "document_key": document_key,
             "description": "SYNTHETIC DEMO ONLY; non-empirical; project-authored CC0 fixture",
             "evidence_type": "synthetic_demo", "evidence_year": "2026", "currency_status": "unverified"},
            "file", FIXTURES / "synthetic_curriculum_demo.txt")
        stages.append({"stage": "curriculum_upload", "http_status": status, "response": redacted_summary(uploaded)})
        curriculum_action = "created"
        operational_job = uploaded.get("operational_job") or {}
        operational_job_id = operational_job.get("job_id")
        if not operational_job_id:
            raise SmokeFailure("Curriculum upload did not return a traceable operational job identifier")
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline:
            job = stage(
                "curriculum_job_poll",
                "GET",
                API + f"/operations/jobs/{operational_job_id}",
            )
            job_status = str(job.get("status") or "unknown")
            if job_status in {"failed", "cancelled"}:
                failure = str(
                    job.get("error_message")
                    or job.get("progress_message")
                    or "no worker error was retained"
                )
                raise SmokeFailure(
                    f"Curriculum operational job {operational_job_id} ended as "
                    f"{job_status}: {failure[:500]}"
                )
            documents = stage("curriculum_inventory_poll", "GET", API + "/curriculum/documents")
            existing = next((d for d in documents if d.get("document_key") == document_key), None)
            if existing:
                break
            if job_status == "completed":
                raise SmokeFailure(
                    f"Curriculum operational job {operational_job_id} completed without "
                    "creating the declared stable document key"
                )
            time.sleep(2)
        if not existing:
            raise SmokeFailure("Curriculum worker did not produce the synthetic document before timeout")
    versions = stage("curriculum_versions", "GET", API + f"/curriculum/documents/{existing['document_id']}/versions")
    if not versions:
        raise SmokeFailure("Synthetic curriculum document has no traceable processed version")
    current_version = max(versions, key=lambda row: row.get("version_number", 0))
    stage("curriculum_skill_processing", "POST", API + "/skills/extract/curriculum",
          payload={"version_id": current_version["version_id"], "limit": 1000})

    # Job upload is synchronous and its connector is responsible for record-level deduplication.
    jobs_before = stage("labour_inventory_before", "GET", API + "/labour-market/jobs?limit=1000")
    demo_ids = {"DEMO-JOB-001", "DEMO-JOB-002", "DEMO-JOB-003"}
    seen_ids = {str(j.get("job_id") or "") for j in jobs_before}
    labour_action = "reused"
    if not demo_ids.issubset(seen_ids):
        status, uploaded = client.multipart(
            API + "/labour-market/jobs/upload",
            {"source_label": "PCLMAS_SYNTHETIC_DEMO_V1", "default_region": "Western Cape", "default_country": "ZA"},
            "file", FIXTURES / "synthetic_vacancies_demo.csv", expected=(201,))
        stages.append({"stage": "labour_upload", "http_status": status, "response": redacted_summary(uploaded)})
        labour_action = "created_or_deduplicated"

    stage("labour_skill_processing", "POST", API + "/labour-market/jobs/skill-pipeline",
          payload={"limit": 1000, "offset": 0})
    stage("curriculum_quality", "GET", API + "/curriculum/quality/summary")
    stage("ingestion_quality", "GET", API + "/ingestion/data-quality/summary")
    stage("skill_inventory", "GET", API + "/skills?limit=200")
    stage("mapping_governance", "GET", API + "/skills/governance/summary")
    stage("processing_readiness", "GET", API + "/processing/validated-regeneration/readiness")
    outputs = {
        "alignment": stage("alignment_output", "GET", API + "/analytics/alignment-scores?limit=100&include_metadata=true"),
        "forecasts": stage("forecast_output", "GET", API + "/analytics/forecasts?limit=100"),
        "recommendations": stage("recommendation_output", "GET", API + "/analytics/recommendations?limit=100"),
        "recommendation_governance": stage("recommendation_governance", "GET", API + "/analytics/recommendation-governance/readiness"),
    }
    audit = stage("audit_trail", "GET", API + "/admin/audit-logs?limit=100")

    # Empty analytical outputs are truthful and do not fail smoke: demo records are never scientific evidence.
    report = {
        "schema_version": "1.0",
        "run_id": "smoke-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "fixture": {"fixture_id": manifest["fixture_id"], "classification": "synthetic_demo_only",
                    "empirical_evidence": False, "sha256": checksums},
        "idempotency": {"curriculum_action": curriculum_action, "labour_action": labour_action,
                        "stable_curriculum_document_key": document_key, "stable_job_record_ids": sorted(demo_ids)},
        "traceability": {"curriculum_document_id": existing["document_id"],
                         "curriculum_version_id": current_version["version_id"],
                         "curriculum_content_hash": current_version.get("content_hash")},
        "stages": stages,
        "outputs": {name: redacted_summary(value) for name, value in outputs.items()},
        "audit": redacted_summary(audit),
        "claim_boundary": "Software demonstration only. No metric, forecast, recommendation, or fixture record is empirical evidence.",
        "status": "passed",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"PASS: synthetic demo smoke report written to {args.report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
