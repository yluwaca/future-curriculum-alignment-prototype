"""Shared reporter for FUTURE diagnostic smoke-test scripts.

Produces a concise JSON object and a human-readable Markdown report, and maps
the collected check results to a strict exit-code contract:

* ``0`` — every required check passed;
* ``1`` — a required functional check failed (an endpoint, page, or database
  probe was reachable but behaved incorrectly);
* ``2`` — configuration or environment is missing (e.g. credentials absent,
  a required setting unset, startup/import failure).

The reporter never accepts secrets and never echoes raw credential material;
callers must put booleans/statuses/lengths in ``details`` only.
"""

from __future__ import annotations

import datetime as _datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_SKIP = "SKIP"

SEVERITY_FUNCTIONAL = "functional"
SEVERITY_CONFIG = "config"


def _timestamp() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds")


@dataclass
class Check:
    id: str
    name: str
    ok: bool
    message: str
    details: Any = None
    severity: str = SEVERITY_FUNCTIONAL
    optional: bool = False

    def status(self) -> str:
        if self.ok:
            return VERDICT_PASS
        if self.optional:
            return VERDICT_SKIP
        return VERDICT_FAIL


@dataclass
class SmokeReport:
    """Ordered collection of checks with JSON + Markdown rendering."""

    name: str
    purpose: str
    checks: List[Check] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, check: Check) -> "SmokeReport":
        self.checks.append(check)
        return self

    def counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {VERDICT_PASS: 0, VERDICT_FAIL: 0, VERDICT_SKIP: 0}
        for check in self.checks:
            counts[check.status()] += 1
        return counts

    def exit_code(self) -> int:
        # Configuration-level failures take priority: if anything required is
        # broken because configuration/environment is missing -> 2.
        for check in self.checks:
            if not check.ok and not check.optional and check.severity == SEVERITY_CONFIG:
                return 2
        for check in self.checks:
            if not check.ok and not check.optional:
                return 1
        return 0

    def verdict(self) -> str:
        code = self.exit_code()
        if code == 0:
            return "PASS"
        if code == 2:
            return "CONFIG_MISSING"
        return "FAIL"

    def payload(self) -> Dict[str, Any]:
        return {
            "report": self.name,
            "generated_at": _timestamp(),
            "verdict": self.verdict(),
            "exit_code": self.exit_code(),
            "counts": self.counts(),
            "purpose": self.purpose,
            "checks": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status(),
                    "severity": c.severity,
                    "optional": c.optional,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
            "notes": self.notes,
            "secrets": False,  # this report intentionally contains no secrets
        }

    def markdown(self) -> str:
        lines: List[str] = []
        lines.append(f"# {self.name}")
        lines.append("")
        lines.append(f"- **Generated:** {_timestamp()}")
        lines.append(f"- **Verdict:** `{self.verdict()}` (exit code {self.exit_code()})")
        counts = self.counts()
        lines.append(
            f"- **Counts:** {counts[VERDICT_PASS]} PASS / {counts[VERDICT_FAIL]} FAIL"
            f" / {counts[VERDICT_SKIP]} SKIP"
        )
        lines.append(f"- **Purpose:** {self.purpose}")
        lines.append("")
        lines.append("| # | check | status | severity | message |")
        lines.append("|---|-------|--------|----------|---------|")
        for index, check in enumerate(self.checks, start=1):
            message = (check.message or "").replace("|", "\\|")
            lines.append(
                f"| {index} | `{check.id}` | `{check.status()}` | {check.severity} | {message} |"
            )
        lines.append("")
        lines.append("## Details")
        lines.append("")
        for check in self.checks:
            if check.status() != VERDICT_PASS or check.details is not None:
                details = json.dumps(check.details, default=str, sort_keys=True) if check.details is not None else "—"
                lines.append(f"### `{check.id}` — {check.status()}")
                lines.append("")
                lines.append(check.message)
                lines.append("")
                lines.append(f"```json\n{details}\n```")
                lines.append("")
        if self.notes:
            lines.append("## Notes")
            lines.append("")
            lines.extend(f"- {note}" for note in self.notes)
            lines.append("")
        lines.append("## Exit codes")
        lines.append("")
        lines.append("- `0` all checks passed")
        lines.append("- `1` functional failure")
        lines.append("- `2` configuration or environment missing")
        return "\n".join(lines)


def write_artifacts(report: SmokeReport, out_dir: Path, stem: str) -> Dict[str, str]:
    """Write ``<stem>.json`` and ``<stem>.md`` into ``out_dir``; return the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report.payload(), indent=2, default=str), encoding="utf-8")
    md_path.write_text(report.markdown(), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}