"""Dispatch service — creates jobs and assigns them to idle agents.

Follows the incident_service.py pattern: constructor injection, callbacks, logging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from legion.domain.agent import Agent, AgentStatus
from legion.domain.job import Job, JobStatus, JobType
from legion.services.exceptions import AgentNotFoundError, DispatchError
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository

logger = logging.getLogger(__name__)

# Callback type aliases
OnJobDispatched = Callable[[Job, Agent], None]
OnNoAgentsAvailable = Callable[[Job], None]


class DispatchService:
    """Coordinates job creation, dispatch, and lifecycle."""

    def __init__(
        self,
        fleet_repo: FleetRepository,
        job_repo: JobRepository,
        *,
        on_job_dispatched: OnJobDispatched | None = None,
        on_no_agents_available: OnNoAgentsAvailable | None = None,
    ) -> None:
        self.fleet_repo = fleet_repo
        self.job_repo = job_repo
        self._on_dispatched = on_job_dispatched
        self._on_no_agents = on_no_agents_available

    def create_job(
        self,
        org_id: str,
        cluster_group_id: str,
        job_type: JobType,
        payload: str,
    ) -> Job:
        job = Job(
            org_id=org_id,
            cluster_group_id=cluster_group_id,
            type=job_type,
            payload=payload,
        )
        self.job_repo.save(job)
        logger.info("Job created: %s (%s)", job.id, job.type.value)
        return job

    def dispatch_pending(self, cluster_group_id: str) -> list[tuple[Job, Agent]]:
        """Assign pending jobs to idle agents in the given cluster group."""
        pending = self.job_repo.list_pending(cluster_group_id)
        idle = list(self.fleet_repo.list_idle_agents(cluster_group_id))
        dispatched: list[tuple[Job, Agent]] = []

        for job in pending:
            if not idle:
                if self._on_no_agents:
                    self._on_no_agents(job)
                continue

            agent = idle.pop(0)
            job.dispatch_to(agent.id)
            agent.go_busy(job.id)
            self.job_repo.save(job)
            self.fleet_repo.save_agent(agent)
            dispatched.append((job, agent))
            logger.info("Dispatched job %s to agent %s", job.id, agent.id)

            if self._on_dispatched:
                self._on_dispatched(job, agent)

        return dispatched

    def complete_job(self, job_id: str, result: str) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        job.complete(result)
        self.job_repo.save(job)

        if job.agent_id:
            agent = self.fleet_repo.get_agent(job.agent_id)
            if agent:
                agent.go_idle()
                self.fleet_repo.save_agent(agent)

        logger.info("Job completed: %s", job_id)
        return job

    def fail_job(self, job_id: str, error: str) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        job.fail(error)
        self.job_repo.save(job)

        if job.agent_id:
            agent = self.fleet_repo.get_agent(job.agent_id)
            if agent:
                agent.go_idle()
                self.fleet_repo.save_agent(agent)

        logger.info("Job failed: %s — %s", job_id, error)
        return job

    def register_agent(
        self,
        cluster_group_id: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> Agent:
        agent = Agent(
            cluster_group_id=cluster_group_id,
            name=name,
            capabilities=capabilities or [],
            status=AgentStatus.IDLE,
        )
        self.fleet_repo.save_agent(agent)
        logger.info("Agent registered: %s (%s)", agent.id, agent.name)
        return agent

    def heartbeat(self, agent_id: str) -> Agent:
        agent = self.fleet_repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")

        agent.heartbeat()
        self.fleet_repo.save_agent(agent)
        return agent

    def reassign_disconnected(self, agent_id: str) -> list[Job]:
        """Revert DISPATCHED/RUNNING jobs for a disconnected agent back to PENDING."""
        jobs = self.job_repo.list_by_agent(agent_id)
        reverted: list[Job] = []
        for job in jobs:
            if job.status in (JobStatus.DISPATCHED, JobStatus.RUNNING):
                job.status = JobStatus.PENDING
                job.agent_id = None
                job.dispatched_at = None
                job.updated_at = datetime.now(timezone.utc)
                self.job_repo.save(job)
                reverted.append(job)
        return reverted
