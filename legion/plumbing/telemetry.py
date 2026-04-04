"""Optional Prometheus metrics facade with silent no-op fallbacks."""

from __future__ import annotations

from typing import Any


class _NoOpMetric:
    def labels(self, *_args: Any, **_kwargs: Any) -> _NoOpMetric:
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def set(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class NoOpCounter(_NoOpMetric):
    pass


class NoOpHistogram(_NoOpMetric):
    pass


class NoOpGauge(_NoOpMetric):
    pass

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    _HAS_PROMETHEUS = True
except ImportError:  # pragma: no cover - exercised in conditional tests
    _HAS_PROMETHEUS = False

    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    def generate_latest() -> bytes:
        return b""


def _counter(name: str, description: str, labelnames: tuple[str, ...] = ()) -> Any:
    if _HAS_PROMETHEUS:
        return Counter(name, description, labelnames)
    return _NO_OP_COUNTER


def _histogram(name: str, description: str, labelnames: tuple[str, ...] = ()) -> Any:
    if _HAS_PROMETHEUS:
        return Histogram(name, description, labelnames)
    return _NO_OP_HISTOGRAM


def _gauge(name: str, description: str, labelnames: tuple[str, ...] = ()) -> Any:
    if _HAS_PROMETHEUS:
        return Gauge(name, description, labelnames)
    return _NO_OP_GAUGE


_NO_OP_COUNTER = NoOpCounter() if not _HAS_PROMETHEUS else None
_NO_OP_HISTOGRAM = NoOpHistogram() if not _HAS_PROMETHEUS else None
_NO_OP_GAUGE = NoOpGauge() if not _HAS_PROMETHEUS else None

jobs_created_total = _counter(
    "jobs_created_total",
    "Total jobs created by organization and job type.",
    ("org_id", "job_type"),
)
jobs_completed_total = _counter(
    "jobs_completed_total",
    "Total jobs completed by organization, job type, and status.",
    ("org_id", "job_type", "status"),
)
job_duration_seconds = _histogram(
    "job_duration_seconds",
    "Time between job creation and terminal completion.",
    ("job_type",),
)
dispatch_latency_seconds = _histogram(
    "dispatch_latency_seconds",
    "Latency for dispatch operations.",
)
active_agents = _gauge(
    "active_agents",
    "Current active agents by group and status.",
    ("agent_group_id", "status"),
)
api_requests_total = _counter(
    "api_requests_total",
    "Total API requests by method, path, and status code.",
    ("method", "path", "status_code"),
)
api_request_duration_seconds = _histogram(
    "api_request_duration_seconds",
    "HTTP request duration by method and path.",
    ("method", "path"),
)
sessions_created_total = _counter(
    "sessions_created_total",
    "Total sessions created by organization and agent group.",
    ("org_id", "agent_group_id"),
)


def metrics_available() -> bool:
    """Return whether prometheus_client is installed and active."""
    return _HAS_PROMETHEUS


def render_metrics() -> tuple[bytes, str]:
    """Render Prometheus exposition bytes and content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
