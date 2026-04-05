"""Dispatch service — creates jobs and assigns them to idle agents.

Follows the incident_service.py pattern: constructor injection, callbacks, logging.
"""

from __future__ import annotations

from collections import Counter
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from legion.domain.agent import Agent, AgentStatus
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.session import Session
from legion.plumbing import telemetry
from legion.services.exceptions import AgentNotFoundError, DispatchError
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository
from legion.services.session_repository import SessionRepository

logger = logging.getLogger(__name__)

# Callback type aliases
OnJobDispatched = Callable[[Job, Agent], None]
OnNoAgentsAvailable = Callable[[Job], None]


def _observe_job_duration(job: Job) -> None:
    if job.completed_at is None:
        return
    telemetry.job_duration_seconds.labels(job.type.value).observe(
        (job.completed_at - job.created_at).total_seconds(),
    )


def _snapshot_active_agent_counts(
    fleet_repo: FleetRepository,
    agent_group_id: str,
) -> dict[str, int]:
    counts = Counter(agent.status.value for agent in fleet_repo.list_agents(agent_group_id))
    return {status.value: counts.get(status.value, 0) for status in AgentStatus}


class DispatchService:
    """Coordinates job creation, dispatch, and lifecycle."""

    def __init__(
        self,
        fleet_repo: FleetRepository,
        job_repo: JobRepository,
        session_repo: SessionRepository | None = None,
        *,
        on_job_dispatched: OnJobDispatched | None = None,
        on_no_agents_available: OnNoAgentsAvailable | None = None,
    ) -> None:
        self.fleet_repo = fleet_repo
        self.job_repo = job_repo
        self.session_repo = session_repo
        self._on_dispatched = on_job_dispatched
        self._on_no_agents = on_no_agents_available
        self._active_agent_counts: dict[str, dict[str, int]] = {}

    def _ensure_active_agent_counts(self, agent_group_id: str) -> None:
        if agent_group_id in self._active_agent_counts:
            return

        counts = _snapshot_active_agent_counts(self.fleet_repo, agent_group_id)
        self._active_agent_counts[agent_group_id] = counts
        for status in AgentStatus:
            telemetry.active_agents.labels(agent_group_id, status.value).set(
                counts[status.value],
            )

    def _record_active_agent_addition(
        self,
        agent_group_id: str,
        status: AgentStatus,
    ) -> None:
        self._ensure_active_agent_counts(agent_group_id)
        counts = self._active_agent_counts[agent_group_id]
        counts[status.value] = counts.get(status.value, 0) + 1
        telemetry.active_agents.labels(agent_group_id, status.value).set(
            counts[status.value],
        )

    def _record_active_agent_transition(
        self,
        agent_group_id: str,
        previous: AgentStatus,
        current: AgentStatus,
    ) -> None:
        if previous == current:
            return

        self._ensure_active_agent_counts(agent_group_id)
        counts = self._active_agent_counts[agent_group_id]
        counts[previous.value] = counts.get(previous.value, 0) - 1
        counts[current.value] = counts.get(current.value, 0) + 1
        telemetry.active_agents.labels(agent_group_id, previous.value).set(
            counts[previous.value],
        )
        telemetry.active_agents.labels(agent_group_id, current.value).set(
            counts[current.value],
        )

    def create_job(
        self,
        org_id: str,
        agent_group_id: str,
        job_type: JobType,
        payload: str,
        *,
        session_id: str | None = None,
        event_id: str | None = None,
        required_capabilities: list[str] | None = None,
    ) -> Job:
        if self.session_repo is None:
            raise DispatchError("session_repo is required for job creation")

        auto_created_session_id: str | None = None
        if session_id is None:
            session = Session(org_id=org_id, agent_group_id=agent_group_id)
            self.session_repo.save(session)
            session_id = session.id
            auto_created_session_id = session.id
        else:
            existing_session = self.session_repo.get_by_id(session_id)
            if existing_session is None:
                raise DispatchError(f"Session {session_id} not found")
            if (
                existing_session.org_id != org_id
                or existing_session.agent_group_id != agent_group_id
            ):
                raise DispatchError(
                    f"Session {session_id} does not belong to org/group {org_id}/{agent_group_id}",
                )
        job = Job(
            org_id=org_id,
            agent_group_id=agent_group_id,
            session_id=session_id,
            event_id=event_id,
            type=job_type,
            payload=payload,
            required_capabilities=required_capabilities or [],
        )
        try:
            self.job_repo.save(job)
        except Exception:
            if auto_created_session_id is not None:
                try:
                    self.session_repo.delete(auto_created_session_id)
                except Exception:
                    logger.exception(
                        "Failed to rollback auto-created session %s after job save failure",
                        auto_created_session_id,
                    )
            raise
        telemetry.jobs_created_total.labels(org_id, job_type.value).inc()
        logger.info("Job created: %s (%s)", job.id, job.type.value)
        return job

    def dispatch_pending(self, agent_group_id: str) -> list[tuple[Job, Agent]]:
        """Assign pending jobs to idle agents in the given cluster group."""
        start = time.perf_counter()
        self._ensure_active_agent_counts(agent_group_id)
        pending = self.job_repo.list_pending(agent_group_id)
        idle = list(self.fleet_repo.list_idle_agents(agent_group_id))
        dispatched: list[tuple[Job, Agent]] = []

        for job in pending:
            if not idle:
                if self._on_no_agents:
                    self._on_no_agents(job)
                continue

            agent = idle.pop(0)
            previous_status = agent.status
            job.dispatch_to(agent.id)
            agent.go_busy(job.id)
            self.job_repo.save(job)
            self.fleet_repo.save_agent(agent)
            self._record_active_agent_transition(
                agent_group_id,
                previous_status,
                agent.status,
            )
            dispatched.append((job, agent))
            logger.info("Dispatched job %s to agent %s", job.id, agent.id)

            if self._on_dispatched:
                self._on_dispatched(job, agent)

        telemetry.dispatch_latency_seconds.observe(time.perf_counter() - start)
        return dispatched

    def complete_job(self, job_id: str, result: str) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        job.complete(result)
        self.job_repo.save(job)
        telemetry.jobs_completed_total.labels(job.org_id, job.type.value, job.status.value).inc()
        _observe_job_duration(job)

        if job.agent_id:
            agent = self.fleet_repo.get_agent(job.agent_id)
            if agent:
                previous_status = agent.status
                agent.go_idle()
                self.fleet_repo.save_agent(agent)
                self._record_active_agent_transition(
                    agent.agent_group_id,
                    previous_status,
                    agent.status,
                )

        logger.info("Job completed: %s", job_id)
        return job

    def fail_job(self, job_id: str, error: str) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        job.fail(error)
        self.job_repo.save(job)
        telemetry.jobs_completed_total.labels(job.org_id, job.type.value, job.status.value).inc()
        _observe_job_duration(job)

        if job.agent_id:
            agent = self.fleet_repo.get_agent(job.agent_id)
            if agent:
                previous_status = agent.status
                agent.go_idle()
                self.fleet_repo.save_agent(agent)
                self._record_active_agent_transition(
                    agent.agent_group_id,
                    previous_status,
                    agent.status,
                )

        logger.info("Job failed: %s — %s", job_id, error)
        return job

    def register_agent(
        self,
        agent_group_id: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> Agent:
        agent = Agent(
            agent_group_id=agent_group_id,
            name=name,
            capabilities=capabilities or [],
            status=AgentStatus.IDLE,
        )
        self.fleet_repo.save_agent(agent)
        self._record_active_agent_addition(agent_group_id, agent.status)
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
