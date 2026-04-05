"""Dispatch service — creates jobs and assigns them to idle agents.

Follows the incident_service.py pattern: constructor injection, callbacks, logging.
"""

from __future__ import annotations

from collections import Counter
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from legion.domain.agent import Agent, AgentStatus
from legion.domain.agent_auth import AgentGroupTokenRotationResult, AgentRegistrationResult, AgentSessionToken
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.session import Session
from legion.plumbing import telemetry
from legion.plumbing.tokens import generate_token, hash_token
from legion.services.agent_session_repository import AgentSessionRepository
from legion.services.exceptions import (
    AgentGroupNotFoundError,
    AgentNotFoundError,
    DispatchError,
    InvalidRegistrationTokenError,
    InvalidSessionTokenError,
    SessionTokenMismatchError,
)
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
        agent_session_repo: AgentSessionRepository | None = None,
        *,
        agent_session_token_ttl_seconds: int = 3600,
        on_job_dispatched: OnJobDispatched | None = None,
        on_no_agents_available: OnNoAgentsAvailable | None = None,
    ) -> None:
        self.fleet_repo = fleet_repo
        self.job_repo = job_repo
        self.session_repo = session_repo
        self.agent_session_repo = agent_session_repo
        self._agent_session_token_ttl_seconds = agent_session_token_ttl_seconds
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

            required = set(job.required_capabilities)
            capable_idx = next(
                (
                    i
                    for i, candidate in enumerate(idle)
                    if required <= set(candidate.capabilities)
                ),
                None,
            )
            if capable_idx is None:
                telemetry.dispatch_capability_skips_total.labels(agent_group_id).inc()
                if self._on_no_agents:
                    self._on_no_agents(job)
                continue

            agent = idle.pop(capable_idx)
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

    def complete_job(self, job_id: str, result: str, *, agent_id: str | None = None) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        if agent_id is not None and job.agent_id != agent_id:
            raise DispatchError(
                f"Agent {agent_id} is not assigned to job {job_id}"
            )

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

    def fail_job(self, job_id: str, error: str, *, agent_id: str | None = None) -> Job:
        job = self.job_repo.get_by_id(job_id)
        if job is None:
            raise DispatchError(f"Job {job_id} not found")

        if agent_id is not None and job.agent_id != agent_id:
            raise DispatchError(
                f"Agent {agent_id} is not assigned to job {job_id}"
            )

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

    def rotate_agent_group_registration_token(self, agent_group_id: str) -> AgentGroupTokenRotationResult:
        agent_group = self.fleet_repo.get_agent_group(agent_group_id)
        if agent_group is None:
            raise AgentGroupNotFoundError(f"AgentGroup {agent_group_id} not found")

        now = datetime.now(timezone.utc)
        raw_token = generate_token()
        agent_group.registration_token_hash = hash_token(raw_token)
        agent_group.registration_token_rotated_at = now
        agent_group.updated_at = now
        self.fleet_repo.save_agent_group(agent_group)
        logger.info("Rotated registration token for agent group %s", agent_group_id)
        return AgentGroupTokenRotationResult(
            agent_group=agent_group,
            registration_token=raw_token,
        )

    def register_agent_with_token(
        self,
        registration_token: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> AgentRegistrationResult:
        if self.agent_session_repo is None:
            raise DispatchError("agent_session_repo is required for agent registration")

        token_hash = hash_token(registration_token)
        agent_group = self.fleet_repo.get_agent_group_by_registration_token_hash(token_hash)
        if agent_group is None:
            raise InvalidRegistrationTokenError("Invalid registration token")

        existing_agent = next(
            (
                agent
                for agent in self.fleet_repo.list_agents(agent_group.id)
                if agent.name == name
            ),
            None,
        )
        if existing_agent is None:
            agent = Agent(
                agent_group_id=agent_group.id,
                name=name,
                capabilities=capabilities or [],
                status=AgentStatus.IDLE,
            )
            self.fleet_repo.save_agent(agent)
            self._record_active_agent_addition(agent.agent_group_id, agent.status)
        else:
            agent = existing_agent
            self._ensure_active_agent_counts(agent_group.id)
            previous_status = agent.status
            agent.agent_group_id = agent_group.id
            agent.name = name
            agent.capabilities = capabilities or []
            agent.go_idle()
            self.fleet_repo.save_agent(agent)
            self._record_active_agent_transition(agent.agent_group_id, previous_status, agent.status)

        self.agent_session_repo.delete_for_agent(agent.id)
        now = datetime.now(timezone.utc)
        raw_session_token = generate_token()
        expires_at = now + timedelta(seconds=self._agent_session_token_ttl_seconds)
        session_token = AgentSessionToken(
            agent_id=agent.id,
            token_hash=hash_token(raw_session_token),
            expires_at=expires_at,
        )
        self.agent_session_repo.save(session_token)

        logger.info("Agent registered via token: %s", agent.id)
        return AgentRegistrationResult(
            agent=agent,
            session_token=raw_session_token,
            session_token_expires_at=expires_at,
        )

    def authenticate_agent_session(self, agent_id: str, session_token: str) -> Agent:
        if self.agent_session_repo is None:
            raise DispatchError("agent_session_repo is required for agent websocket auth")

        token_hash = hash_token(session_token)
        stored_token = self.agent_session_repo.get_active_by_token_hash(token_hash)
        if stored_token is None:
            raise InvalidSessionTokenError("Invalid or expired session token")
        if stored_token.agent_id != agent_id:
            raise SessionTokenMismatchError("Session token does not belong to the requested agent")

        agent = self.fleet_repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")
        return agent

    def heartbeat(self, agent_id: str) -> Agent:
        agent = self.fleet_repo.get_agent(agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent {agent_id} not found")

        agent.heartbeat()
        self.fleet_repo.save_agent(agent)
        return agent

    def disconnect_agent(self, agent_id: str) -> list[Job]:
        """Mark an agent offline and re-queue its in-flight work."""

        agent = self.fleet_repo.get_agent(agent_id)
        if agent is not None:
            previous_status = agent.status
            agent.go_offline()
            self.fleet_repo.save_agent(agent)
            self._record_active_agent_transition(
                agent.agent_group_id,
                previous_status,
                agent.status,
            )

        reverted = self.reassign_disconnected(agent_id)
        logger.info("Agent disconnected: %s", agent_id)
        return reverted

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
