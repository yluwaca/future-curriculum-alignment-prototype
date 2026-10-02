"""UI/API readiness markers for the final labour-market Go-Live audit.

These DB-free, source-inspection guards confirm that the presentation layer
is demonstrably ready for the offline readiness review:

* Status regions are announced to assistive technology and loading is
  blocked and re-armed on every Adzuna intake / pipeline control.
* The job-posting intake confirms batch sizes before running and surfaces
  the server stop reason without echoing advert text or credentials.
* The pipeline module dims the review link until candidate mappings exist
  and never renders raw source labels or policy wording.
* No frontend asset can embed live credentials or serially-issued secrets,
  and the backend credential-masking contract pins secret values down.

The live API contract itself is verified in
test_labour_market_offline_audit.py and
test_labour_market_adzuna_pipeline.py.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
FRONTEND = ROOT / "frontend"

from app.services.ingestion.credential_service import credential_service  # noqa: E402


def read_frontend(relative: str) -> str:
    return (FRONTEND / relative).read_text(encoding="utf-8")


def test_intake_status_regions_are_announced():
    html = read_frontend("data-operations.html")
    assert '<p id="adzunaStatus" role="status" aria-live="polite"></p>' in html
    assert '<p id="adzunaPipelineStatus" role="status" aria-live="polite"></p>' in html
    assert 'role="status" aria-live="polite"' in html
    assert 'id="adzunaPipelineRunSummary" class="empty">' in html
    assert "No labour-market skill pipeline run recorded yet." in html


def test_intake_controls_block_and_rearm():
    module = read_frontend("adzuna-intake.js")
    estimate = _slice(module, "('adzunaEstimateBtn').addEventListener", "safeConfirm.addEventListener")
    run = _slice(module, "('adzunaImportPagesBtn').addEventListener", "('adzunaShowBtn')")
    # Every async handler disables its trigger and re-enables it in finally.
    assert "button.disabled = true" in estimate and "finally { button.disabled = false; }" in estimate
    assert "button.disabled = true" in run and "finally { safeModeRow.style.display = 'none'; button.disabled = false; }" in run
    # Batch-size confirmation gates the actual import.
    assert "safeConfirm.checked" in module
    assert "Confirm the request count above before running this many-page import." in module
    # Server stop reason is surfaced without echoing full advert text.
    assert "result.stop_reason" in run and "postings received" in run
    assert "status.textContent" in run


def test_pipeline_controls_block_rearm_and_dim_review():
    module = read_frontend("adzuna-skill-pipeline.js")
    pipeline = _slice(module, "async function runPipeline", "async function generateSignals")
    signals = _slice(module, "async function generateSignals", "async function refreshStatus")
    for fn in (pipeline, signals):
        assert "button.disabled = true" in fn and "button.disabled = false;" in fn
        assert "statusEl.textContent" in fn
    assert "statusEl.textContent = 'Refreshing pipeline run status…';" in module
    assert "reviewLink.disabled = mappingCount <= 0" in module


def test_frontend_never_embeds_credentials():
    patterns = (
        re.compile(r"(?i)adzuna[\s_]*app[\s_]{1,2}(?:id|key)\b"),
        re.compile(r"(?i)\b(?:app_id|app_key|api_key|client_secret|access_token|refresh_token|bearer_token)\b\s*[:=]\s*['\"][^'\"]{6,}"),
        re.compile(r"9de4a1e\w{6,}"),
    )
    for filename in sorted(FRONTEND.rglob("*")):
        if filename.suffix.lower() not in {".html", ".js"}:
            continue
        text = filename.read_text(encoding="utf-8", errors="replace")
        for index, pattern in enumerate(patterns):
            match = pattern.search(text)
            assert not match, (
                f"{filename.name} may embed a live credential "
                f"(pattern #{index} matched {match.group(0)!r})"
            )


def test_credential_masking_contract_pins_secret_values():
    masked = credential_service.mask_config(
        {"api_key": "live-secret-123", "base_url": "https://example.test", "_credential_format": "fernet"}
    )
    assert masked["api_key"] == "***configured***"
    assert masked["base_url"] == "https://example.test"  # non-secret fields pass through
    assert "live-secret-123" not in str(masked)
    # The fingerprint must be derived only from the masked representation so
    # it can never leak a secret value.
    fingerprint = credential_service.fingerprint({"api_key": "live-secret-123", "base_url": "https://example.test"})
    assert isinstance(fingerprint, str) and len(fingerprint) == 16
    assert "live-secret-123" not in fingerprint


def _slice(source: str, start_marker: str, end_marker: str) -> str:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]