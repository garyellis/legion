"""Session service — manages conversational context with agent affinity.

Follows the incident_service.py pattern: constructor injection, callbacks, logging.
"""

from __future__ import annotations

import logging
from typing import Callable

from legion.domain.session import Session, SessionStatus
from legion.plumbing import telemetry
from legion.services.exceptions import SessionError
from legion.services.fleet_repository import FleetRepository
from legion.services.session_link_repository import SessionLinkRepository
from legion.services.session_repository import SessionRepository

logger = logging.getLogger(__name__)

OnSessionCreated = Callable[[Session], None]


class SessionService:
    """Coordinates session lifecycle with agent affinity."""

    def __init__(
        self,
        session_repo: SessionRepository,
        fleet_repo: FleetRepository,
        session_link_repo: SessionLinkRepository | None = None,
        *,
        on_session_created: OnSessionCreated | None = None,
    ) -> None:
        self.session_repo = session_repo
        self.fleet_repo = fleet_repo
        self.session_link_repo = session_link_repo
        self._on_created = on_session_created

    def get_or_create(
        self,
        org_id: str,
        agent_group_id: str,
        channel_id: str,
        thread_ts: str,
    ) -> tuple[Session, bool]:
        """Return (session, created).

        If an active session exists for this thread, return it.
        Otherwise create a new one.
        """
        if self.session_link_repo is None:
            raise SessionError("SessionLinkRepository is required for get_or_create")

        existing_session_id = self.session_link_repo.get_session_id(channel_id, thread_ts)
        if existing_session_id is not None:
            existing = self.session_repo.get_by_id(existing_session_id)
            if existing is not None and existing.status == SessionStatus.ACTIVE:
                return existing, False

        session = Session(
            org_id=org_id,
            agent_group_id=agent_group_id,
        )
        self.session_repo.save(session)
        self.session_link_repo.save_link(session.id, channel_id, thread_ts)
        telemetry.sessions_created_total.labels(org_id, agent_group_id).inc()
        logger.info("Session created: %s", session.id)

        if self._on_created:
            self._on_created(session)

        return session, True

    def pin_agent(self, session_id: str, agent_id: str) -> Session:
        """Pin session to an agent on first dispatch."""
        session = self.session_repo.get_by_id(session_id)
        if session is None:
            raise SessionError(f"Session {session_id} not found")

        session.pin_agent(agent_id)
        self.session_repo.save(session)
        logger.info("Session %s pinned to agent %s", session_id, agent_id)
        return session

    def close_session(self, session_id: str) -> Session:
        """Close a session."""
        session = self.session_repo.get_by_id(session_id)
        if session is None:
            raise SessionError(f"Session {session_id} not found")

        session.close()
        self.session_repo.save(session)
        logger.info("Session closed: %s", session_id)
        return session

    def touch(self, session_id: str) -> Session:
        """Update last_activity timestamp."""
        session = self.session_repo.get_by_id(session_id)
        if session is None:
            raise SessionError(f"Session {session_id} not found")

        session.touch()
        self.session_repo.save(session)
        return session
