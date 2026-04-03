"""Tests for DispatchService."""

import pytest

from legion.domain.agent import AgentStatus
from legion.domain.job import JobStatus, JobType
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import AgentNotFoundError, DispatchError
from legion.services.fleet_repository import InMemoryFleetRepository
from legion.services.job_repository import InMemoryJobRepository


@pytest.fixture()
def fleet_repo():
    return InMemoryFleetRepository()


@pytest.fixture()
def job_repo():
    return InMemoryJobRepository()


@pytest.fixture()
def service(fleet_repo, job_repo):
    return DispatchService(fleet_repo, job_repo)


class TestDispatchService:
    def test_create_job(self, service, job_repo):
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert fired")
        assert job.status == JobStatus.PENDING
        assert job.payload == "alert fired"
        assert job_repo.get_by_id(job.id) is not None

    def test_dispatch_pending_assigns_agent(self, service, fleet_repo):
        agent = service.register_agent("cg-1", "agent-01", ["k8s"])
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")

        dispatched = service.dispatch_pending("cg-1")
        assert len(dispatched) == 1
        d_job, d_agent = dispatched[0]
        assert d_job.status == JobStatus.DISPATCHED
        assert d_job.agent_id == agent.id
        assert d_agent.status == AgentStatus.BUSY
        assert d_agent.current_job_id == job.id

    def test_dispatch_pending_no_agents_fires_callback(self, fleet_repo, job_repo):
        no_agent_jobs = []
        svc = DispatchService(
            fleet_repo, job_repo,
            on_no_agents_available=lambda job: no_agent_jobs.append(job.id),
        )
        job = svc.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        svc.dispatch_pending("cg-1")
        assert job.id in no_agent_jobs

    def test_dispatch_pending_fires_dispatched_callback(self, fleet_repo, job_repo):
        dispatched_pairs = []
        svc = DispatchService(
            fleet_repo, job_repo,
            on_job_dispatched=lambda j, a: dispatched_pairs.append((j.id, a.id)),
        )
        agent = svc.register_agent("cg-1", "agent-01")
        svc.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        svc.dispatch_pending("cg-1")
        assert len(dispatched_pairs) == 1

    def test_complete_job(self, service, fleet_repo):
        agent = service.register_agent("cg-1", "agent-01")
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("cg-1")

        # Start the job
        job.start()

        completed = service.complete_job(job.id, "incident resolved")
        assert completed.status == JobStatus.COMPLETED
        assert completed.result == "incident resolved"

        reloaded_agent = fleet_repo.get_agent(agent.id)
        assert reloaded_agent.status == AgentStatus.IDLE
        assert reloaded_agent.current_job_id is None

    def test_fail_job(self, service, fleet_repo):
        agent = service.register_agent("cg-1", "agent-01")
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("cg-1")
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
        agent = service.register_agent("cg-1", "agent-01", ["k8s", "logs"])
        assert agent.status == AgentStatus.IDLE
        assert agent.capabilities == ["k8s", "logs"]
        assert fleet_repo.get_agent(agent.id) is not None

    def test_heartbeat(self, service):
        agent = service.register_agent("cg-1", "agent-01")
        assert agent.last_heartbeat is None
        updated = service.heartbeat(agent.id)
        assert updated.last_heartbeat is not None

    def test_heartbeat_nonexistent_raises(self, service):
        with pytest.raises(AgentNotFoundError):
            service.heartbeat("nope")

    def test_reassign_disconnected_reverts_dispatched(self, service, job_repo):
        agent = service.register_agent("cg-1", "agent-01")
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("cg-1")
        assert job.status == JobStatus.DISPATCHED

        reverted = service.reassign_disconnected(agent.id)
        assert len(reverted) == 1
        assert reverted[0].status == JobStatus.PENDING
        assert reverted[0].agent_id is None

    def test_reassign_disconnected_ignores_completed(self, service, job_repo):
        agent = service.register_agent("cg-1", "agent-01")
        job = service.create_job("org-1", "cg-1", JobType.TRIAGE, "alert")
        service.dispatch_pending("cg-1")
        service.complete_job(job.id, "done")

        reverted = service.reassign_disconnected(agent.id)
        assert len(reverted) == 0
