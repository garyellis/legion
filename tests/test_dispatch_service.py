"""Tests for DispatchService."""

from __future__ import annotations

import pytest

from legion.domain.agent import AgentStatus
from legion.domain.job import JobStatus, JobType
from legion.domain.session import Session
from legion.plumbing.database import create_all, create_engine
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import AgentNotFoundError, DispatchError
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
def service(fleet_repo, job_repo, session_repo):
    return DispatchService(fleet_repo, job_repo, session_repo)


class TestDispatchService:
    def test_create_job(self, service, job_repo, session_repo):
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert fired")
        assert job.status == JobStatus.PENDING
        assert job.payload == "alert fired"
        assert session_repo.get_by_id(job.session_id) is not None
        assert job_repo.get_by_id(job.id) is not None

    def test_create_job_preserves_explicit_session_and_fields(self, service):
        session = Session(org_id="org-1", agent_group_id="ag-1")
        service.session_repo.save(session)
        job = service.create_job(
            "org-1",
            "ag-1",
            JobType.INVESTIGATE,
            "alert fired",
            session_id=session.id,
            event_id="event-123",
            required_capabilities=["kubernetes"],
        )
        assert job.session_id == session.id
        assert job.event_id == "event-123"
        assert job.required_capabilities == ["kubernetes"]

    def test_create_job_requires_session_repo(
        self,
        fleet_repo,
        job_repo,
    ):
        service = DispatchService(fleet_repo, job_repo)
        with pytest.raises(DispatchError, match="session_repo is required"):
            service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert fired")

    def test_create_job_rejects_unknown_session_id(self, service):
        with pytest.raises(DispatchError, match="Session missing-session not found"):
            service.create_job(
                "org-1",
                "ag-1",
                JobType.TRIAGE,
                "alert fired",
                session_id="missing-session",
            )

    def test_create_job_rejects_session_from_different_org_or_group(self, service):
        session = Session(org_id="org-2", agent_group_id="ag-2")
        service.session_repo.save(session)

        with pytest.raises(DispatchError, match="does not belong to org/group"):
            service.create_job(
                "org-1",
                "ag-1",
                JobType.TRIAGE,
                "alert fired",
                session_id=session.id,
            )

    def test_create_job_rolls_back_auto_created_session_on_job_save_failure(
        self,
        service,
        job_repo,
        session_repo,
        monkeypatch: pytest.MonkeyPatch,
    ):
        def fail_save(_job):
            raise RuntimeError("db write failed")

        monkeypatch.setattr(job_repo, "save", fail_save)

        with pytest.raises(RuntimeError, match="db write failed"):
            service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert fired")

        assert session_repo.list_active() == []

    def test_dispatch_pending_assigns_agent(self, service, fleet_repo):
        agent = service.register_agent("ag-1", "agent-01", ["k8s"])
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_job.status == JobStatus.DISPATCHED
        assert d_job.agent_id == agent.id
        assert d_agent.status == AgentStatus.BUSY
        assert d_agent.current_job_id == job.id

    def test_dispatch_pending_no_agents_fires_callback(self, fleet_repo, job_repo, session_repo):
        no_agent_jobs = []
        svc = DispatchService(
            fleet_repo, job_repo, session_repo,
            on_no_agents_available=lambda job: no_agent_jobs.append(job.id),
        )
        job = svc.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        svc.dispatch_pending("ag-1")
        assert job.id in no_agent_jobs

    def test_dispatch_pending_fires_dispatched_callback(self, fleet_repo, job_repo, session_repo):
        dispatched_pairs = []
        svc = DispatchService(
            fleet_repo, job_repo, session_repo,
            on_job_dispatched=lambda j, a: dispatched_pairs.append((j.id, a.id)),
        )
        agent = svc.register_agent("ag-1", "agent-01")
        svc.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        svc.dispatch_pending("ag-1")
        assert len(dispatched_pairs) == 1

    def test_complete_job(self, service, fleet_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")

        # Start the job
        job.start()

        completed = service.complete_job(job.id, "incident resolved")
        assert completed.status == JobStatus.COMPLETED
        assert completed.result == "incident resolved"

        reloaded_agent = fleet_repo.get_agent(agent.id)
        assert reloaded_agent.status == AgentStatus.IDLE
        assert reloaded_agent.current_job_id is None

    def test_fail_job(self, service, fleet_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")
        job.start()

        failed = service.fail_job(job.id, "connection timeout")
        assert failed.status == JobStatus.FAILED
        assert failed.error == "connection timeout"

        reloaded_agent = fleet_repo.get_agent(agent.id)
        assert reloaded_agent.status == AgentStatus.IDLE

    def test_complete_nonexistent_raises(self, service):
        with pytest.raises(DispatchError):
            service.complete_job("nope", "result")

    def test_fail_nonexistent_raises(self, service):
        with pytest.raises(DispatchError):
            service.fail_job("nope", "error")

    def test_register_agent(self, service, fleet_repo):
        agent = service.register_agent("ag-1", "agent-01", ["k8s", "logs"])
        assert agent.status == AgentStatus.IDLE
        assert agent.capabilities == ["k8s", "logs"]
        assert fleet_repo.get_agent(agent.id) is not None

    def test_heartbeat(self, service):
        agent = service.register_agent("ag-1", "agent-01")
        assert agent.last_heartbeat is None
        updated = service.heartbeat(agent.id)
        assert updated.last_heartbeat is not None

    def test_heartbeat_nonexistent_raises(self, service):
        with pytest.raises(AgentNotFoundError):
            service.heartbeat("nope")

    def test_reassign_disconnected_reverts_dispatched(self, service, job_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")
        # Re-read from repo — SQLite returns new instances, not mutated originals
        job = job_repo.get_by_id(job.id)
        assert job.status == JobStatus.DISPATCHED

        reverted = service.reassign_disconnected(agent.id)
        assert len(reverted) == 1
        assert reverted[0].status == JobStatus.PENDING
        assert reverted[0].agent_id is None

    def test_reassign_disconnected_ignores_completed(self, service, job_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")
        service.complete_job(job.id, "done")

        reverted = service.reassign_disconnected(agent.id)
        assert len(reverted) == 0

    def test_active_agent_counts_are_initialized_once(
        self,
        service,
        fleet_repo,
        monkeypatch: pytest.MonkeyPatch,
    ):
        original_list_agents = fleet_repo.list_agents
        calls = []

        def counting_list_agents(agent_group_id):
            calls.append(agent_group_id)
            return original_list_agents(agent_group_id)

        monkeypatch.setattr(fleet_repo, "list_agents", counting_list_agents)

        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")
        job.start()
        service.complete_job(job.id, "done")

        assert calls == ["ag-1"]
        assert agent.status == AgentStatus.IDLE
