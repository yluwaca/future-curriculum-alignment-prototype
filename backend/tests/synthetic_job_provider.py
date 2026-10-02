"""Deterministic synthetic job-board API server for end-to-end tests.

Serves the same Adzuna-shaped ``{"results": [...], "count": N}`` search payloads
over plain HTTP on a loopback port, using only the standard library. The
synthetic provider ("provider=synthetic") reads its base URL from
``FUTURE_SYNTHETIC_JOBS_BASE_URL`` and its page number lives in the URL path,
exactly like the real Adzuna search endpoint.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Set


SYNTHETIC_TITLES = [
    "Data Engineer",
    "Data Analyst",
    "Business Intelligence Developer",
    "Machine Learning Engineer",
    "Cybersecurity Analyst",
]

# Descriptions deliberately embed phrase-boundary-safe skill terms that the
# labour-market pipeline's CURATED_TEXT_SKILLS table recognises.
SYNTHETIC_DESCRIPTIONS = [
    "Build data pipelines with Python, SQL and cloud: AWS services, PostgreSQL and data analysis.",
    "Apply machine learning and statistics to business intelligence dashboards with Power BI and Tableau.",
    "Analyse job adverts using Python, SQL and Cybersecurity practices across cloud platforms.",
]


def synthetic_page_1_default() -> List[Dict]:
    rows = []
    created = "2026-08-03T09:00:00Z"
    for index, (title, description) in enumerate(zip(SYNTHETIC_TITLES[:3], SYNTHETIC_DESCRIPTIONS), start=1):
        rows.append(synthetic_row(f"syn-1-{index}", created, title, description))
    return rows


def synthetic_page_2_default() -> List[Dict]:
    rows = []
    created = "2026-08-17T09:00:00Z"
    for index, (title, description) in enumerate(zip(SYNTHETIC_TITLES[3:], SYNTHETIC_DESCRIPTIONS[1:]), start=1):
        rows.append(synthetic_row(f"syn-2-{index}", created, title, description))
    return rows


def synthetic_row(ad_id: str, created: str, title: str, description: str) -> Dict:
    return {
        "id": ad_id,
        "title": title,
        "company": {"display_name": "Synthetic Example Co"},
        "description": description,
        "created": created,
        "redirect_url": f"https://example.invalid/synthetic/{ad_id}",
        "location": {"display_name": "Cape Town, Western Cape", "area": ["Cape Town", "Western Cape"]},
        "category": {"label": "IT Jobs"},
        "contract_type": "full_time",
        "salary_min": 55000,
        "salary_max": 90000,
    }


def catalogue(rows_per_page: int = 3, total_pages: int = 2,
              empty_pages: Optional[Set[int]] = None) -> Dict[int, List[Dict]]:
    """Return ``{page_number: [rows, ...]}`` with deterministic ad ids."""
    empty_pages = empty_pages or set()
    pages: Dict[int, List[Dict]] = {}
    created_days = ("2026-08-03", "2026-08-17", "2026-08-26")
    for page in range(1, total_pages + 1):
        if page in empty_pages:
            pages[page] = []
            continue
        rows: List[Dict] = []
        for index in range(1, rows_per_page + 1):
            title = SYNTHETIC_TITLES[(page + index - 1) % len(SYNTHETIC_TITLES)]
            description = SYNTHETIC_DESCRIPTIONS[(page + index - 1) % len(SYNTHETIC_DESCRIPTIONS)]
            day = created_days[(page + index - 1) % len(created_days)]
            rows.append(synthetic_row(f"syn-{page}-{index}", f"{day}T09:00:00Z", title, description))
        pages[page] = rows
    return pages


class SyntheticJobServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(BaseHTTPRequestHandler):
    server_version = "SyntheticJobBoard/1.0"

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        parts = [part for part in path.split("/") if part]
        try:
            page = int(parts[-1])
        except (IndexError, ValueError):
            self._send({"results": [], "count": 0}, status=404)
            return

        server = self.server  # type: SyntheticJobServer
        server.hits.append(page)
        if page in server.malformed_responses:
            entry = server.malformed_responses[page]
            if isinstance(entry, tuple):
                raw_body, content_type = entry
                payload = raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
            else:
                payload = entry if isinstance(entry, bytes) else entry.encode("utf-8")
                content_type = "text/plain"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if page in server.error_once_pages and not server.error_fired.get(page):
            server.error_fired[page] = True
            self._send({"error": "temporary upstream failure"}, status=500)
            return
        if page in server.always_error_pages:
            self._send({"error": "permanent upstream failure"}, status=500)
            return
        if page in server.empty_pages:
            self._send({"count": 0, "results": []})
            return
        rows = server.pages.get(page, [])
        self._send({"count": server.total_count, "results": rows})

    def _send(self, payload: Dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class SyntheticJobBoard:
    """Context manager serving a deterministic synthetic search endpoint."""

    def __init__(
        self,
        rows_per_page: int = 3,
        total_pages: int = 2,
        empty_pages: Optional[Set[int]] = None,
        error_once_pages: Optional[Set[int]] = None,
        always_error_pages: Optional[Set[int]] = None,
        malformed_responses: Optional[Dict[int, str]] = None,
    ) -> None:
        self.pages = catalogue(rows_per_page=rows_per_page, total_pages=total_pages,
                               empty_pages=empty_pages)
        self.empty_pages = empty_pages or set()
        self.error_once_pages = error_once_pages or set()
        self.always_error_pages = always_error_pages or set()
        self.malformed_responses = malformed_responses or {}
        self.total_count = sum(len(rows) for rows in self.pages.values())
        self.httpd = SyntheticJobServer(("127.0.0.1", 0), _Handler)
        self.httpd.pages = self.pages
        self.httpd.empty_pages = self.empty_pages
        self.httpd.error_once_pages = self.error_once_pages
        self.httpd.always_error_pages = self.always_error_pages
        self.httpd.malformed_responses = self.malformed_responses
        self.httpd.error_fired = {}
        self.httpd.total_count = self.total_count
        self.httpd.hits = []
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "SyntheticJobBoard":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> bool:
        self.httpd.shutdown()
        self.httpd.server_close()
        return False