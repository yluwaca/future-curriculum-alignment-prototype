"""Focused checks for live system-performance measurements."""

from __future__ import annotations

from app.core.metrics import MetricsCollector
from app.services import system_performance_service as performance_module


def test_metrics_summary_includes_endpoint_p95():
    collector = MetricsCollector()
    for duration in (10, 20, 30, 40, 100):
        collector.record_request("GET", "/test", 200, duration)

    endpoint = collector.get_summary()["response_times"]["/test"]

    assert endpoint["count"] == 5
    assert endpoint["p95_ms"] == 100
    assert endpoint["max_ms"] == 100


def test_resource_snapshot_has_production_dashboard_contract():
    result = performance_module.system_performance_service._resources()

    assert result["status"] in {"healthy", "warning", "critical"}
    for key in (
        "cpu_percent",
        "memory_percent",
        "memory_used_bytes",
        "memory_total_bytes",
        "disk_percent",
        "disk_used_bytes",
        "disk_total_bytes",
    ):
        assert key in result
