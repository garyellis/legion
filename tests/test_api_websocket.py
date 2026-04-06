"""WebSocket integration tests for the API surface."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from legion.api.config import APIConfig
from legion.api.main import create_app
from legion.domain.agent import Agent, AgentStatus
from legion.domain.agent_auth import AgentSessionToken
from legion.domain.agent_group import AgentGroup
from legion.domain.job import Job, JobStatus, JobType
from legion.plumbing.database import create_all, create_engine
from legion.plumbing.tokens import generate_token, hash_token
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository


def _wait_for(predicate: Callable[[], Any], *, timeout: float = 5.0, interval: float = 0.01) -> Any:
    """Poll *predicate* until it returns a truthy value or *timeout* elapses.

    Used to synchronise with server-side ``finally`` blocks that run
    ``run_in_executor`` work after the WebSocket connection closes.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def fleet_repo(_engine):
    return SQLiteFleetRepository(_engine)


@pytest.fixture()
def job_repo(_engine):
    return SQLiteJobRepository(_engine)


@pytest.fixture()
def session_repo(_engine):
    return SQLiteSessionRepository(_engine)


@pytest.fixture()
def agent_session_repo(_engine):
    return SQLiteAgentSessionRepository(_engine)


@pytest.fixture()
def app(fleet_repo, job_repo, session_repo, agent_session_repo):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        session_repo=session_repo,
        agent_session_repo=agent_session_repo,
        api_config=APIConfig(
            agent_session_token_ttl_seconds=90,
            agent_heartbeat_interval_seconds=45,
        ),
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _seed_agent_and_token(client, fleet_repo, *, agent_id: str, agent_group_id: str = "ag-1", name: str = "ws-agent") -> str:
    agent = Agent(agent_group_id=agent_group_id, name=name, id=agent_id)
    fleet_repo.save_agent(agent)

    raw_token = generate_token()
    client.app.state.agent_session_repo.save(
        AgentSessionToken(
            agent_id=agent_id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    )
    return raw_token


def _seed_agent_group(fleet_repo, *, agent_group_id: str = "ag-1") -> None:
    fleet_repo.save_agent_group(
        AgentGroup(
            id=agent_group_id,
            org_id="00000000-0000-0000-0000-000000000000",
            project_id="00000000-0000-0000-0000-000000000001",
            name="group",
            slug="group",
            environment="dev",
            provider="aks",
        ),
    )


class TestAgentWebSocket:
    def test_rotate_agent_group_token_route(self, client, fleet_repo):
        _seed_agent_group(fleet_repo)

        resp = client.post("/agent-groups/ag-1/token")
        assert resp.status_code == 201
        body = resp.json()
        assert body["agent_group_id"] == "ag-1"
        assert body["registration_token"]

    def test_register_agent_route_returns_session_token(self, client, fleet_repo):
        _seed_agent_group(fleet_repo)
        rotation = client.app.state.dispatch_service.rotate_agent_group_registration_token("ag-1")
        before = datetime.now(timezone.utc)

        resp = client.post(
            "/agents/register",
            json={
                "registration_token": rotation.registration_token,
                "name": "ws-agent-registered",
                "capabilities": ["k8s"],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["agent"]["name"] == "ws-agent-registered"
        assert body["session_token"]
        assert body["config"]["heartbeat_interval_seconds"] == 45
        assert body["config"]["websocket_path"] == f"/ws/agents/{body['agent']['id']}"
        expires_at = datetime.fromisoformat(body["session_token_expires_at"])
        assert expires_at >= before + timedelta(seconds=89)
        assert expires_at <= before + timedelta(seconds=91)

    def test_connect_marks_idle(self, client, fleet_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-1")

        with client.websocket_connect(
            "/ws/agents/agent-ws-1",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ws:
            saw_idle = _wait_for(
                lambda: fleet_repo.get_agent("agent-ws-1").status == AgentStatus.IDLE,
            )
            assert saw_idle, "Agent did not reach IDLE within timeout"
            # Send a heartbeat to confirm server is still processing
            ws.send_text(json.dumps({"type": "heartbeat"}))

    def test_heartbeat_updates_timestamp(self, client, fleet_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-2")

        with client.websocket_connect(
            "/ws/agents/agent-ws-2",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ws:
            ws.send_text(json.dumps({"type": "heartbeat"}))
            # Wait for the server to process the heartbeat via run_in_executor
            _wait_for(lambda: fleet_repo.get_agent("agent-ws-2").last_heartbeat is not None)

        reloaded = fleet_repo.get_agent("agent-ws-2")
        assert reloaded.last_heartbeat is not None

    def test_malformed_messages_are_ignored_without_dropping_connection(self, client, fleet_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-2b")

        with client.websocket_connect(
            "/ws/agents/agent-ws-2b",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ws:
            ws.send_text("{bad-json")
            ws.send_text(json.dumps({"type": "job_result", "job_id": "missing-job"}))
            ws.send_text(json.dumps({"type": "heartbeat"}))
            # Wait for the server to process the heartbeat via run_in_executor
            _wait_for(lambda: fleet_repo.get_agent("agent-ws-2b").last_heartbeat is not None)

        reloaded = fleet_repo.get_agent("agent-ws-2b")
        assert reloaded.last_heartbeat is not None

    def test_disconnect_marks_offline(self, client, fleet_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-3")

        with client.websocket_connect(
            "/ws/agents/agent-ws-3",
            headers={"Authorization": f"Bearer {raw_token}"},
        ):
            pass  # connect then immediately disconnect

        _wait_for(lambda: fleet_repo.get_agent("agent-ws-3").status == AgentStatus.OFFLINE)
        reloaded = fleet_repo.get_agent("agent-ws-3")
        assert reloaded.status == AgentStatus.OFFLINE

    def test_disconnect_reverts_dispatched_jobs(self, client, fleet_repo, job_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-4")

        job = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-1",
            type=JobType.TRIAGE, payload="alert",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-4",
        )
        job_repo.save(job)

        with client.websocket_connect(
            "/ws/agents/agent-ws-4",
            headers={"Authorization": f"Bearer {raw_token}"},
        ):
            pass  # disconnect

        _wait_for(lambda: job_repo.get_by_id(job.id).status == JobStatus.PENDING)
        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.PENDING
        assert reloaded_job.agent_id is None

    def test_job_result_completes_job(self, client, fleet_repo, job_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-5")

        job = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-2",
            type=JobType.QUERY, payload="check pods",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-5",
        )
        job_repo.save(job)

        with client.websocket_connect(
            "/ws/agents/agent-ws-5",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ws:
            ws.send_text(json.dumps({
                "type": "job_result", "job_id": job.id, "result": "all pods healthy",
            }))
            # Wait for the server to process the message via run_in_executor
            _wait_for(lambda: job_repo.get_by_id(job.id).status == JobStatus.COMPLETED)

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.COMPLETED
        assert reloaded_job.result == "all pods healthy"

    def test_job_failed_marks_failed(self, client, fleet_repo, job_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-6")

        job = Job(
            org_id="org-1", agent_group_id="ag-1", session_id="session-3",
            type=JobType.QUERY, payload="check pods",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-6",
        )
        job_repo.save(job)

        with client.websocket_connect(
            "/ws/agents/agent-ws-6",
            headers={"Authorization": f"Bearer {raw_token}"},
        ) as ws:
            ws.send_text(json.dumps({
                "type": "job_failed", "job_id": job.id, "error": "timeout",
            }))
            # Wait for the server to process the message via run_in_executor
            _wait_for(lambda: job_repo.get_by_id(job.id).status == JobStatus.FAILED)

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.FAILED
        assert reloaded_job.error == "timeout"

    def test_invalid_session_token_rejected(self, client, fleet_repo):
        _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-7")

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/ws/agents/agent-ws-7",
                headers={"Authorization": "Bearer bad-token"},
            ):
                pass
        assert exc_info.value.code == 4001

    def test_mismatched_session_token_rejected(self, client, fleet_repo):
        raw_token = _seed_agent_and_token(client, fleet_repo, agent_id="agent-ws-8")

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/ws/agents/agent-ws-999",
                headers={"Authorization": f"Bearer {raw_token}"},
            ):
                pass
        assert exc_info.value.code == 4003
