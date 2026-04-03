"""WebSocket integration tests for the API surface."""

import json

import pytest
from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.domain.agent import Agent, AgentStatus
from legion.domain.job import Job, JobStatus, JobType
from legion.plumbing.database import create_all, create_engine
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository


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
def app(fleet_repo, job_repo, session_repo):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        session_repo=session_repo,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


class TestAgentWebSocket:
    def test_connect_marks_idle(self, client, fleet_repo):
        agent = Agent(cluster_group_id="cg-1", name="ws-agent", id="agent-ws-1")
        fleet_repo.save_agent(agent)

        with client.websocket_connect("/ws/agents/agent-ws-1"):
            reloaded = fleet_repo.get_agent("agent-ws-1")
            assert reloaded.status == AgentStatus.IDLE

    def test_heartbeat_updates_timestamp(self, client, fleet_repo):
        agent = Agent(cluster_group_id="cg-1", name="ws-agent", id="agent-ws-2")
        fleet_repo.save_agent(agent)

        with client.websocket_connect("/ws/agents/agent-ws-2") as ws:
            ws.send_text(json.dumps({"type": "heartbeat"}))
            # Send another message to ensure the heartbeat was processed
            ws.send_text(json.dumps({"type": "heartbeat"}))

        reloaded = fleet_repo.get_agent("agent-ws-2")
        assert reloaded.last_heartbeat is not None

    def test_disconnect_marks_offline(self, client, fleet_repo):
        agent = Agent(cluster_group_id="cg-1", name="ws-agent", id="agent-ws-3")
        fleet_repo.save_agent(agent)

        with client.websocket_connect("/ws/agents/agent-ws-3"):
            pass  # connect then immediately disconnect

        reloaded = fleet_repo.get_agent("agent-ws-3")
        assert reloaded.status == AgentStatus.OFFLINE

    def test_disconnect_reverts_dispatched_jobs(self, client, fleet_repo, job_repo):
        agent = Agent(
            cluster_group_id="cg-1", name="ws-agent", id="agent-ws-4",
            status=AgentStatus.IDLE,
        )
        fleet_repo.save_agent(agent)

        job = Job(
            org_id="org-1", cluster_group_id="cg-1",
            type=JobType.TRIAGE, payload="alert",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-4",
        )
        job_repo.save(job)

        with client.websocket_connect("/ws/agents/agent-ws-4"):
            pass  # disconnect

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.PENDING
        assert reloaded_job.agent_id is None

    def test_job_result_completes_job(self, client, fleet_repo, job_repo):
        agent = Agent(
            cluster_group_id="cg-1", name="ws-agent", id="agent-ws-5",
            status=AgentStatus.IDLE,
        )
        fleet_repo.save_agent(agent)

        job = Job(
            org_id="org-1", cluster_group_id="cg-1",
            type=JobType.QUERY, payload="check pods",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-5",
        )
        job_repo.save(job)

        with client.websocket_connect("/ws/agents/agent-ws-5") as ws:
            ws.send_text(json.dumps({
                "type": "job_result", "job_id": job.id, "result": "all pods healthy",
            }))
            # Send heartbeat to ensure previous message was processed
            ws.send_text(json.dumps({"type": "heartbeat"}))

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.COMPLETED
        assert reloaded_job.result == "all pods healthy"

    def test_job_failed_marks_failed(self, client, fleet_repo, job_repo):
        agent = Agent(
            cluster_group_id="cg-1", name="ws-agent", id="agent-ws-6",
            status=AgentStatus.IDLE,
        )
        fleet_repo.save_agent(agent)

        job = Job(
            org_id="org-1", cluster_group_id="cg-1",
            type=JobType.QUERY, payload="check pods",
            status=JobStatus.DISPATCHED, agent_id="agent-ws-6",
        )
        job_repo.save(job)

        with client.websocket_connect("/ws/agents/agent-ws-6") as ws:
            ws.send_text(json.dumps({
                "type": "job_failed", "job_id": job.id, "error": "timeout",
            }))
            ws.send_text(json.dumps({"type": "heartbeat"}))

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.FAILED
        assert reloaded_job.error == "timeout"
