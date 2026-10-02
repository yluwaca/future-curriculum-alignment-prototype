"""
In-memory metrics collector for request tracking.
Thread-safe counters and histograms for monitoring.
"""

import time
import threading
import math
from collections import defaultdict
from datetime import datetime, timezone


class MetricsCollector:
    """Thread-safe in-memory metrics collector."""

    def __init__(self):
        self._lock = threading.Lock()
        self._request_count = defaultdict(int)
        self._error_count = defaultdict(int)
        self._status_count = defaultdict(int)
        self._endpoint_timings = defaultdict(list)
        self._start_time = time.time()
        self._total_requests = 0
        self._total_errors = 0

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ):
        """Record a completed request."""
        with self._lock:
            self._total_requests += 1
            self._request_count[f"{method} {path}"] += 1
            self._status_count[status_code] += 1

            if status_code >= 400:
                self._total_errors += 1
                self._error_count[f"{method} {path}"] += 1

            self._endpoint_timings[path].append(duration_ms)
            if len(self._endpoint_timings[path]) > 1000:
                self._endpoint_timings[path] = self._endpoint_timings[path][-500:]

    def get_summary(self) -> dict:
        """Get current metrics summary."""
        with self._lock:
            uptime = time.time() - self._start_time
            avg_timings = {}
            for path, timings in self._endpoint_timings.items():
                if timings:
                    ordered = sorted(timings)
                    p95_index = min(
                        len(ordered) - 1,
                        max(0, math.ceil(len(ordered) * 0.95) - 1),
                    )
                    avg_timings[path] = {
                        "avg_ms": round(sum(timings) / len(timings), 2),
                        "p95_ms": round(ordered[p95_index], 2),
                        "min_ms": round(min(timings), 2),
                        "max_ms": round(max(timings), 2),
                        "count": len(timings),
                    }

            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": self._total_requests,
                "total_errors": self._total_errors,
                "error_rate": round(
                    self._total_errors / max(self._total_requests, 1) * 100, 2
                ),
                "status_codes": dict(self._status_count),
                "top_endpoints": dict(
                    sorted(
                        self._request_count.items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:20]
                ),
                "response_times": avg_timings,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._request_count.clear()
            self._error_count.clear()
            self._status_count.clear()
            self._endpoint_timings.clear()
            self._start_time = time.time()
            self._total_requests = 0
            self._total_errors = 0


metrics = MetricsCollector()
