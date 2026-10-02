"""Release 1 durable operational job safety tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.operational_job_service import OperationalJobService
from app.routers.curriculum import sanitised_endpoint_url


def test_job_fingerprint_is_stable_across_parameter_order():
    service = OperationalJobService()
    first = service.fingerprint(
        "processing.full",
        {"limit": 100, "horizon_periods": 4},
    )
    second = service.fingerprint(
        "processing.full",
        {"horizon_periods": 4, "limit": 100},
    )
    assert first == second


def test_job_fingerprint_changes_with_parameters():
    service = OperationalJobService()
    first = service.fingerprint("processing.full", {"limit": 100})
    second = service.fingerprint("processing.full", {"limit": 101})
    assert first != second


def test_job_serialisation_exposes_progress_and_manifest():
    now = datetime.now(timezone.utc)
    job = SimpleNamespace(
        job_id=uuid4(),
        job_type="processing.readiness",
        queue_name="default",
        status="completed",
        requested_by="reviewer",
        parameters={"limit": 1},
        progress_current=100,
        progress_total=100,
        progress_message="Completed successfully",
        attempt_number=1,
        max_attempts=3,
        retry_of_job_id=None,
        result={"report_id": "report-1"},
        run_manifest={"worker_id": "worker-1"},
        error_summary=None,
        worker_id="worker-1",
        created_at=now,
        started_at=now,
        completed_at=now,
        next_attempt_at=None,
        cancel_requested_at=None,
    )

    payload = OperationalJobService.to_dict(job)

    assert payload["status"] == "completed"
    assert payload["progress_current"] == 100
    assert payload["result"]["report_id"] == "report-1"
    assert payload["run_manifest"]["worker_id"] == "worker-1"


def test_worker_status_is_stopped_before_start():
    service = OperationalJobService()
    assert service.worker_status()["status"] == "stopped"
    assert service.worker_status()["lanes"] == {}


def test_model_training_uses_a_separate_compute_lane():
    service = OperationalJobService()
    assert service.COMPUTE_JOB_TYPES == (
        "model.train.xgboost",
        "model.train.lstm",
    )


def test_worker_registers_durable_ingestion_handlers():
    service = OperationalJobService()
    assert "ingestion.statssa" in service.handlers
    assert "ingestion.che_vitalstats" in service.handlers
    assert "ingestion.generic_import" in service.handlers
    assert "ingestion.curriculum_upload" in service.handlers
    assert "ingestion.cput_prospectus" in service.handlers
    assert "model.train.xgboost" in service.handlers
    assert "model.train.lstm" in service.handlers
    assert "system.backup.create" in service.handlers
    assert "skills.extract.evidence" in service.handlers


def test_ingestion_parameters_produce_distinct_job_fingerprints():
    service = OperationalJobService()
    first = service.fingerprint(
        "ingestion.che_vitalstats",
        {"ingestion_job_id": str(uuid4()), "start_year": 2022},
    )
    second = service.fingerprint(
        "ingestion.che_vitalstats",
        {"ingestion_job_id": str(uuid4()), "start_year": 2022},
    )
    assert first != second


def test_curriculum_api_metadata_removes_url_secrets():
    safe = sanitised_endpoint_url(
        "https://api-user:api-password@example.org:8443/curriculum"
        "?access_token=secret-value#private"
    )
    assert safe == "https://example.org:8443/curriculum"
    assert "password" not in safe
    assert "secret" not in safe
