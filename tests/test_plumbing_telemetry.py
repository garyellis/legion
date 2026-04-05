"""Tests for optional telemetry plumbing and metrics endpoint."""

from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.domain.job import JobType
from legion.plumbing import telemetry
from legion.plumbing.database import create_all, create_engine
from legion.plumbing.plugins import ToolMeta, get_tool_meta, tool
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository
from legion.services.session_service import SessionService

API_KEY = "test-secret"
TELEMETRY_PATH = Path(__file__).resolve().parent.parent / "legion" / "plumbing" / "telemetry.py"


class _RecorderMetric:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def labels(self, *args: object) -> _RecorderMetric:
        self.calls.append(("labels", args))
        return self

    def inc(self, *args: object) -> None:
        self.calls.append(("inc", args))

    def observe(self, *args: object) -> None:
        self.calls.append(("observe", args))

    def set(self, *args: object) -> None:
        self.calls.append(("set", args))


def _make_repos() -> dict[str, object]:
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return {
        "fleet_repo": SQLiteFleetRepository(engine),
        "job_repo": SQLiteJobRepository(engine),
        "session_repo": SQLiteSessionRepository(engine),
    }


def _load_telemetry_without_prometheus(monkeypatch: pytest.MonkeyPatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "prometheus_client":
            raise ImportError("blocked for test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    spec = importlib.util.spec_from_file_location("test_no_prometheus_telemetry", TELEMETRY_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_without_prometheus_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_telemetry_without_prometheus(monkeypatch)
    assert module.metrics_available() is False


def test_noop_metrics_are_callable() -> None:
    for metric in (telemetry.NoOpCounter(), telemetry.NoOpHistogram(), telemetry.NoOpGauge()):
        metric.labels("a", key="b").inc()
        metric.observe(1.23)
        metric.set(2)


def test_metrics_available_returns_bool() -> None:
    assert isinstance(telemetry.metrics_available(), bool)


def test_render_metrics_returns_bytes_and_content_type() -> None:
    payload, content_type = telemetry.render_metrics()
    assert isinstance(payload, bytes)
    assert isinstance(content_type, str)


def test_tool_decorator_attaches_metadata() -> None:
    @tool("demo", description="example", tags=("ops",), version="2.0")
    def sample() -> str:
        return "ok"

    meta = get_tool_meta(sample)
    assert meta == ToolMeta("demo", "example", ("ops",), "2.0")
    assert sample() == "ok"


def test_get_tool_meta_returns_none_for_undecorated() -> None:
    def plain() -> None:
        return None

    assert get_tool_meta(plain) is None


def test_metrics_endpoint_bypasses_auth() -> None:
    with TestClient(create_app(**_make_repos(), api_key=API_KEY)) as client:
        response = client.get("/metrics")
    assert response.status_code in {200, 501}


def test_metrics_endpoint_501_when_prometheus_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "metrics_available", lambda: False)

    with TestClient(create_app(**_make_repos())) as client:
        response = client.get("/metrics")

    assert response.status_code == 501
    assert response.json() == {"detail": "prometheus_client is not installed"}


def test_metrics_endpoint_returns_prometheus_payload_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry, "metrics_available", lambda: True)
    monkeypatch.setattr(telemetry, "render_metrics", lambda: (b"metric 1\n", "text/plain"))

    with TestClient(create_app(**_make_repos())) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.content == b"metric 1\n"
    assert response.headers["content-type"].startswith("text/plain")


def test_request_metrics_record_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_total = _RecorderMetric()
    request_duration = _RecorderMetric()
    monkeypatch.setattr(telemetry, "api_requests_total", requests_total)
    monkeypatch.setattr(telemetry, "api_request_duration_seconds", request_duration)

    with TestClient(create_app(**_make_repos())) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert ("labels", ("GET", "/health", "200")) in requests_total.calls
    assert ("inc", ()) in requests_total.calls
    assert ("labels", ("GET", "/health")) in request_duration.calls
    assert any(name == "observe" for name, _args in request_duration.calls)


def test_request_metrics_record_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_total = _RecorderMetric()
    request_duration = _RecorderMetric()
    monkeypatch.setattr(telemetry, "api_requests_total", requests_total)
    monkeypatch.setattr(telemetry, "api_request_duration_seconds", request_duration)

    with TestClient(create_app(**_make_repos(), api_key=API_KEY)) as client:
        response = client.get("/organizations/org-123")

    assert response.status_code == 401
    assert ("labels", ("GET", "/organizations/{org_id}", "401")) in requests_total.calls
    assert ("inc", ()) in requests_total.calls
    assert ("labels", ("GET", "/organizations/{org_id}")) in request_duration.calls
    assert any(name == "observe" for name, _args in request_duration.calls)


def test_request_metrics_record_protected_success(monkeypatch: pytest.MonkeyPatch) -> None:
    requests_total = _RecorderMetric()
    request_duration = _RecorderMetric()
    monkeypatch.setattr(telemetry, "api_requests_total", requests_total)
    monkeypatch.setattr(telemetry, "api_request_duration_seconds", request_duration)

    with TestClient(create_app(**_make_repos(), api_key=API_KEY)) as client:
        create_response = client.post(
            "/organizations/",
            json={"name": "Org 1", "slug": "org-1"},
            headers={"X-API-Key": API_KEY},
        )
        assert create_response.status_code == 201
        org_id = create_response.json()["id"]
        response = client.get(f"/organizations/{org_id}", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert ("labels", ("GET", "/organizations/{org_id}", "200")) in requests_total.calls
    assert ("inc", ()) in requests_total.calls
    assert ("labels", ("GET", "/organizations/{org_id}")) in request_duration.calls
    assert any(name == "observe" for name, _args in request_duration.calls)


def test_dispatch_service_increments_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _make_repos()
    jobs_created = _RecorderMetric()
    jobs_completed = _RecorderMetric()
    job_duration = _RecorderMetric()
    active_agents = _RecorderMetric()
    dispatch_latency = _RecorderMetric()

    monkeypatch.setattr("legion.services.dispatch_service.telemetry.jobs_created_total", jobs_created)
    monkeypatch.setattr("legion.services.dispatch_service.telemetry.jobs_completed_total", jobs_completed)
    monkeypatch.setattr("legion.services.dispatch_service.telemetry.job_duration_seconds", job_duration)
    monkeypatch.setattr("legion.services.dispatch_service.telemetry.active_agents", active_agents)
    monkeypatch.setattr("legion.services.dispatch_service.telemetry.dispatch_latency_seconds", dispatch_latency)

    service = DispatchService(
        repos["fleet_repo"],
        repos["job_repo"],
        repos["session_repo"],
    )
    agent = service.register_agent("ag-1", "agent-1")
    job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "payload")
    assert ("labels", ("ag-1", "IDLE")) in active_agents.calls
    assert ("set", (1,)) in active_agents.calls

    service.dispatch_pending("ag-1")
    assert ("labels", ("ag-1", "BUSY")) in active_agents.calls
    assert ("set", (1,)) in active_agents.calls
    assert any(name == "observe" for name, _args in dispatch_latency.calls)

    job.start()
    service.complete_job(job.id, "done")
    assert ("labels", ("ag-1", "IDLE")) in active_agents.calls

    assert ("labels", ("org-1", "TRIAGE")) in jobs_created.calls
    assert ("inc", ()) in jobs_created.calls
    assert ("labels", ("org-1", "TRIAGE", "COMPLETED")) in jobs_completed.calls
    assert ("inc", ()) in jobs_completed.calls
    assert any(name == "observe" for name, _args in job_duration.calls)


def test_session_service_increments_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _make_repos()
    sessions_created = _RecorderMetric()
    monkeypatch.setattr("legion.services.session_service.telemetry.sessions_created_total", sessions_created)

    service = SessionService(repos["session_repo"], repos["fleet_repo"])
    _session, created = service.get_or_create("org-1", "ag-1", "C123", "1234.5678")

    assert created is True
    assert ("labels", ("org-1", "ag-1")) in sessions_created.calls
    assert ("inc", ()) in sessions_created.calls


@pytest.mark.skipif(not telemetry.metrics_available(), reason="prometheus_client not installed")
def test_real_prometheus_render_includes_registered_metrics() -> None:
    payload, content_type = telemetry.render_metrics()
    assert b"jobs_created_total" in payload
    assert "text/plain" in content_type
