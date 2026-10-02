"""Unit tests for the Adzuna SA diagnostic probe.

Scripts are exercised without any network call: responses are faked, so no
credential is used, printed, or captured.  Exactly two response shapes are
covered: an HTTP 403 HTML error (the previously-crashing case) and a
successful JSON response.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "AdzunaAPI.py"
)
SPEC = importlib.util.spec_from_file_location("adzuna_api", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        body: str,
        content_type: str,
        app_id: str = "test_app_id",
        app_key: str = "test_app_key",
    ):
        self.status_code = status_code
        self.text = body
        self.headers = {"Content-Type": content_type}
        self._app_id = app_id
        self._app_key = app_key

    def json(self):
        import json

        return json.loads(self.text)


def build_fake_session(response: FakeResponse):
    class FakeClient:
        def get(self, url, params=None, timeout=None):
            self.last_url = url
            self.last_params = params
            return response

    return FakeClient()


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Provide non-credential test values so the env gate is satisfied."""
    monkeypatch.setenv("ADZUNA_APP_ID", "mocked_app_id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "mocked_app_key")


def test_403_html_reports_clean_error():
    session = build_fake_session(
        FakeResponse(403, "<html><body>Forbidden</body></html>", "text/html")
    )
    with pytest.raises(MODULE.AdzunaHTTPError) as excinfo:
        MODULE.probe_once("developer", None, 5, session=session)
    assert excinfo.value.status_code == 403
    assert excinfo.value.content_type == "text/html"
    assert "Forbidden" in excinfo.value.prefix


def test_success_json_is_parsed():
    body = '{"count": 5, "results": [{"title": "x"}]}'
    session = build_fake_session(
        FakeResponse(200, body, "application/json")
    )
    result = MODULE.probe_once("developer", "cape town", 5, session=session)
    assert result["status_code"] == 200
    assert result["content_type"] == "application/json"
    assert result["payload"]["count"] == 5


def test_redirected_url_redacts_credentials():
    from urllib.parse import parse_qsl, urlsplit

    query = MODULE.build_query("developer", None, 5, None)
    fake = {**query, "app_id": "super_secret_id", "app_key": "super_secret_key"}
    rendered = MODULE.ADZUNA_SEARCH_ENDPOINT + "?" + "&".join(
        f"{k}={v}" for k, v in fake.items()
    )
    redacted = MODULE.redact(rendered)
    parts = urlsplit(redacted)
    params = dict(parse_qsl(parts.query))
    assert params["app_id"] == "REDACTED"
    assert params["app_key"] == "REDACTED"
    assert "super_secret_id" not in redacted
    assert "super_secret_key" not in redacted


def test_missing_credentials_raises_clean_error(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(MODULE.AdzunaCredentialsError):
        MODULE.request_once(MODULE.build_query("developer", None, 5, None))


def test_dry_run_prints_redacted_url(capsys):
    exit_code = MODULE.main(["--dry-run", "--what", "developer"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "REDACTED" in captured.out
    assert "app_id" in captured.out or "app_key" in captured.out
    assert "super_secret" not in captured.out