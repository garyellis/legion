"""Explicit ORM row registration for shared SQLAlchemy metadata."""

from __future__ import annotations

from legion.services import agent_session_repository  # noqa: F401
from legion.services import audit_event_repository  # noqa: F401
from legion.services import fleet_repository  # noqa: F401
from legion.services import job_repository  # noqa: F401
from legion.services import message_repository  # noqa: F401
from legion.services import repository  # noqa: F401
from legion.services import session_repository  # noqa: F401
from legion.slack.incident import persistence  # noqa: F401
from legion.slack.session import persistence as slack_session_persistence  # noqa: F401


def register_all_models() -> None:
    """Import all ORM row modules so Base.metadata is complete."""
