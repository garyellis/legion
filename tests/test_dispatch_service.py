"""Tests for DispatchService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from legion.domain.agent import AgentStatus
from legion.domain.agent_group import AgentGroup
from legion.domain.job import JobStatus, JobType
from legion.domain.session import Session
from legion.plumbing.database import create_all, create_engine
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import (
    AgentGroupNotFoundError,
    AgentNotFoundError,
    DispatchError,
    InvalidRegistrationTokenError,
)
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
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
def agent_session_repo(_engine):
    return SQLiteAgentSessionRepository(_engine)


@pytest.fixture()
def service(fleet_repo, job_repo, session_repo, agent_session_repo):
    return DispatchService(fleet_repo, job_repo, session_repo, agent_session_repo)


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

    def test_disconnect_agent_marks_offline_and_requeues_running_job(self, service, fleet_repo, job_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("ag-1")
        dispatched_job = job_repo.get_by_id(job.id)
        assert dispatched_job is not None
        dispatched_job.start()
        job_repo.save(dispatched_job)

        reverted = service.disconnect_agent(agent.id)

        reloaded_agent = fleet_repo.get_agent(agent.id)
        assert reloaded_agent is not None
        assert reloaded_agent.status == AgentStatus.OFFLINE
        assert len(reverted) == 1
        assert reverted[0].status == JobStatus.PENDING

    def test_dispatch_pending_matches_agent_by_capabilities(self, service, fleet_repo):
        agent_k8s = service.register_agent("ag-1", "agent-k8s", ["kubernetes", "logs"])
        agent_logs = service.register_agent("ag-1", "agent-logs", ["logs"])
        job = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert",
            required_capabilities=["kubernetes"],
        )

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_agent.id == agent_k8s.id

    def test_dispatch_pending_skips_incapable_agent(self, service, fleet_repo):
        agent_logs = service.register_agent("ag-1", "agent-logs", ["logs"])
        agent_k8s = service.register_agent("ag-1", "agent-k8s", ["kubernetes", "logs"])
        job = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert",
            required_capabilities=["kubernetes"],
        )

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_agent.id == agent_k8s.id

        reloaded_logs = fleet_repo.get_agent(agent_logs.id)
        assert reloaded_logs.status == AgentStatus.IDLE

    def test_dispatch_pending_no_capable_agent_fires_callback(
        self, fleet_repo, job_repo, session_repo,
    ):
        no_agent_jobs = []
        svc = DispatchService(
            fleet_repo, job_repo, session_repo,
            on_no_agents_available=lambda job: no_agent_jobs.append(job.id),
        )
        svc.register_agent("ag-1", "agent-logs", ["logs"])
        job = svc.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert",
            required_capabilities=["kubernetes"],
        )
        svc.dispatch_pending("ag-1")
        assert job.id in no_agent_jobs

        reloaded_job = job_repo.get_by_id(job.id)
        assert reloaded_job.status == JobStatus.PENDING

    def test_dispatch_pending_capable_agent_consumed_by_first_job(
        self, service, fleet_repo, job_repo,
    ):
        service.register_agent("ag-1", "agent-k8s", ["kubernetes"])
        service.register_agent("ag-1", "agent-logs", ["logs"])
        job_a = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-a",
            required_capabilities=["kubernetes"],
        )
        job_b = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-b",
            required_capabilities=["kubernetes"],
        )

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_job.id == job_a.id

        reloaded_b = job_repo.get_by_id(job_b.id)
        assert reloaded_b.status == JobStatus.PENDING

    def test_dispatch_pending_mixed_capabilities_single_cycle(
        self, service, fleet_repo,
    ):
        agent_k8s = service.register_agent("ag-1", "agent-k8s", ["kubernetes"])
        agent_logs = service.register_agent("ag-1", "agent-logs", ["logs"])
        job_a = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-k8s",
            required_capabilities=["kubernetes"],
        )
        job_b = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-logs",
            required_capabilities=["logs"],
        )

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 2

        dispatched_map = {d_job.id: d_agent for d_job, d_agent in dispatched}
        assert dispatched_map[job_a.id].id == agent_k8s.id
        assert dispatched_map[job_b.id].id == agent_logs.id

    def test_dispatch_pending_contention_callback_fires_for_second_job(
        self, fleet_repo, job_repo, session_repo,
    ):
        no_agent_jobs = []
        svc = DispatchService(
            fleet_repo, job_repo, session_repo,
            on_no_agents_available=lambda job: no_agent_jobs.append(job.id),
        )
        svc.register_agent("ag-1", "agent-k8s", ["kubernetes"])
        job_a = svc.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-a",
            required_capabilities=["kubernetes"],
        )
        job_b = svc.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert-b",
            required_capabilities=["kubernetes"],
        )

        dispatched = svc.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        assert dispatched[0][0].id == job_a.id
        assert job_b.id in no_agent_jobs

    def test_dispatch_pending_empty_capabilities_matches_any_agent(self, service, fleet_repo):
        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.TRIAGE, "alert")

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_agent.id == agent.id

    def test_dispatch_pending_requires_all_capabilities(self, service, fleet_repo):
        agent_partial = service.register_agent("ag-1", "agent-partial", ["kubernetes"])
        agent_full = service.register_agent(
            "ag-1", "agent-full", ["kubernetes", "logs", "metrics"],
        )
        job = service.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert",
            required_capabilities=["kubernetes", "logs"],
        )

        dispatched = service.dispatch_pending("ag-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_agent.id == agent_full.id

    def test_dispatch_pending_capability_skip_counter(
        self, fleet_repo, job_repo, session_repo, monkeypatch: pytest.MonkeyPatch,
    ):
        from tests.test_plumbing_telemetry import _RecorderMetric

        skip_counter = _RecorderMetric()
        monkeypatch.setattr(
            "legion.services.dispatch_service.telemetry.dispatch_capability_skips_total",
            skip_counter,
        )

        svc = DispatchService(fleet_repo, job_repo, session_repo)
        svc.register_agent("ag-1", "agent-logs", ["logs"])
        svc.create_job(
            "org-1", "ag-1", JobType.TRIAGE, "alert",
            required_capabilities=["kubernetes"],
        )
        svc.dispatch_pending("ag-1")

        assert ("labels", ("ag-1",)) in skip_counter.calls
        assert ("inc", ()) in skip_counter.calls

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

    def test_rotate_agent_group_registration_token(self, service, fleet_repo):
        fleet_repo.save_agent_group(
            AgentGroup(
                id="ag-1",
                org_id="org-1",
                project_id="proj-1",
                name="group",
                slug="group",
                environment="dev",
                provider="aks",
            ),
        )

        result = service.rotate_agent_group_registration_token("ag-1")

        assert result.agent_group.id == "ag-1"
        assert result.registration_token
        assert fleet_repo.get_agent_group("ag-1").registration_token_hash is not None

    def test_rotate_agent_group_registration_token_missing_group(self, service):
        with pytest.raises(AgentGroupNotFoundError):
            service.rotate_agent_group_registration_token("missing")

    def test_register_agent_with_token(self, service, fleet_repo):
        fleet_repo.save_agent_group(
            AgentGroup(
                id="ag-1",
                org_id="org-1",
                project_id="proj-1",
                name="group",
                slug="group",
                environment="dev",
                provider="aks",
            ),
        )
        rotation = service.rotate_agent_group_registration_token("ag-1")

        result = service.register_agent_with_token(rotation.registration_token, "agent-01", ["k8s"])

        assert result.agent.name == "agent-01"
        assert result.agent.status == AgentStatus.IDLE
        assert result.session_token
        assert result.session_token_expires_at is not None
        assert fleet_repo.list_agents("ag-1")[0].id == result.agent.id

    def test_register_agent_with_token_reuses_existing_agent_id(self, service, fleet_repo):
        fleet_repo.save_agent_group(
            AgentGroup(
                id="ag-1",
                org_id="org-1",
                project_id="proj-1",
                name="group",
                slug="group",
                environment="dev",
                provider="aks",
            ),
        )
        rotation = service.rotate_agent_group_registration_token("ag-1")

        first = service.register_agent_with_token(rotation.registration_token, "agent-01", ["k8s"])
        second = service.register_agent_with_token(rotation.registration_token, "agent-01", ["logs"])

        assert second.agent.id == first.agent.id
        assert second.agent.capabilities == ["logs"]
        assert len(fleet_repo.list_agents("ag-1")) == 1

    def test_register_agent_with_token_rejects_invalid_token(self, service):
        with pytest.raises(InvalidRegistrationTokenError):
            service.register_agent_with_token("bad-token", "agent-01", [])

    def test_register_agent_with_token_uses_configured_session_ttl(
        self,
        fleet_repo,
        job_repo,
        session_repo,
        agent_session_repo,
    ):
        service = DispatchService(
            fleet_repo,
            job_repo,
            session_repo,
            agent_session_repo,
            agent_session_token_ttl_seconds=90,
        )
        fleet_repo.save_agent_group(
            AgentGroup(
                id="ag-1",
                org_id="org-1",
                project_id="proj-1",
                name="group",
                slug="group",
                environment="dev",
                provider="aks",
            ),
        )
        rotation = service.rotate_agent_group_registration_token("ag-1")

        before = datetime.now(timezone.utc)
        result = service.register_agent_with_token(rotation.registration_token, "agent-01", ["k8s"])
        after = datetime.now(timezone.utc)

        assert before + timedelta(seconds=90) <= result.session_token_expires_at + timedelta(seconds=1)
        assert result.session_token_expires_at <= after + timedelta(seconds=91)
