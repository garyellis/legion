"""Tests for fleet domain models: Organization, AgentGroup, Agent, Job."""

from legion.domain.agent import Agent, AgentStatus
from legion.domain.agent_group import AgentGroup, ExecutionMode
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.organization import Organization


class TestOrganization:
    def test_creation_defaults(self):
        org = Organization(name="Acme", slug="acme")
        assert org.id  # non-empty UUID
        assert org.name == "Acme"
        assert org.slug == "acme"
        assert org.created_at.tzinfo is not None
        assert org.updated_at.tzinfo is not None


class TestAgentGroup:
    def test_creation_defaults(self):
        ag = AgentGroup(
            org_id="org-1", name="US West", slug="us-west",
            environment="prod", provider="eks",
        )
        assert ag.id
        assert ag.org_id == "org-1"
        assert ag.environment == "prod"
        assert ag.provider == "eks"
        assert ag.execution_mode == ExecutionMode.READ_ONLY

    def test_execution_mode_override(self):
        ag = AgentGroup(
            org_id="org-1", name="Dev", slug="dev",
            environment="dev", provider="aks",
            execution_mode=ExecutionMode.AUTO_EXECUTE,
        )
        assert ag.execution_mode == ExecutionMode.AUTO_EXECUTE


class TestAgent:
    def test_creation_defaults(self):
        agent = Agent(agent_group_id="ag-1", name="agent-01")
        assert agent.status == AgentStatus.OFFLINE
        assert agent.current_job_id is None
        assert agent.capabilities == []
        assert agent.last_heartbeat is None

    def test_offline_to_idle(self):
        agent = Agent(agent_group_id="ag-1", name="a")
        agent.go_idle()
        assert agent.status == AgentStatus.IDLE
        assert agent.current_job_id is None

    def test_idle_to_busy(self):
        agent = Agent(agent_group_id="ag-1", name="a")
        agent.go_idle()
        agent.go_busy("job-1")
        assert agent.status == AgentStatus.BUSY
        assert agent.current_job_id == "job-1"

    def test_busy_to_idle(self):
        agent = Agent(agent_group_id="ag-1", name="a")
        agent.go_idle()
        agent.go_busy("job-1")
        agent.go_idle()
        assert agent.status == AgentStatus.IDLE
        assert agent.current_job_id is None

    def test_any_to_offline(self):
        agent = Agent(agent_group_id="ag-1", name="a")
        agent.go_idle()
        agent.go_busy("job-1")
        agent.go_offline()
        assert agent.status == AgentStatus.OFFLINE
        assert agent.current_job_id is None

    def test_heartbeat_updates_timestamp(self):
        agent = Agent(agent_group_id="ag-1", name="a")
        assert agent.last_heartbeat is None
        agent.heartbeat()
        assert agent.last_heartbeat is not None
        assert agent.last_heartbeat.tzinfo is not None


class TestJob:
    def test_creation_defaults(self):
        job = Job(
            org_id="org-1", agent_group_id="ag-1",
            type=JobType.TRIAGE, payload="alert fired",
        )
        assert job.status == JobStatus.PENDING
        assert job.agent_id is None
        assert job.result is None
        assert job.dispatched_at is None

    def test_lifecycle_pending_to_completed(self):
        job = Job(
            org_id="org-1", agent_group_id="ag-1",
            type=JobType.QUERY, payload="check logs",
        )
        job.dispatch_to("agent-1")
        assert job.status == JobStatus.DISPATCHED
        assert job.agent_id == "agent-1"
        assert job.dispatched_at is not None

        job.start()
        assert job.status == JobStatus.RUNNING

        job.complete("all clear")
        assert job.status == JobStatus.COMPLETED
        assert job.result == "all clear"
        assert job.completed_at is not None

    def test_fail_sets_error(self):
        job = Job(
            org_id="org-1", agent_group_id="ag-1",
            type=JobType.TRIAGE, payload="alert",
        )
        job.dispatch_to("agent-1")
        job.start()
        job.fail("timeout")
        assert job.status == JobStatus.FAILED
        assert job.error == "timeout"
        assert job.completed_at is not None

    def test_cancel_from_pending(self):
        job = Job(
            org_id="org-1", agent_group_id="ag-1",
            type=JobType.TRIAGE, payload="alert",
        )
        job.cancel()
        assert job.status == JobStatus.CANCELLED
        assert job.completed_at is not None

    def test_cancel_from_dispatched(self):
        job = Job(
            org_id="org-1", agent_group_id="ag-1",
            type=JobType.TRIAGE, payload="alert",
        )
        job.dispatch_to("agent-1")
        job.cancel()
        assert job.status == JobStatus.CANCELLED
