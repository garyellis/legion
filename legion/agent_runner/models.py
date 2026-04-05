"""Typed protocol and session models for the agent runner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from pydantic import BaseModel

from legion.core.fleet_api.models import AgentRegistrationResponse
from legion.domain.job import JobType


def _resolve_websocket_url(api_url: str, websocket_path: str) -> str:
    ws_target = websocket_path.strip()
    parsed = urlsplit(ws_target)
    if parsed.scheme in {"ws", "wss"}:
        return ws_target

    base = urlsplit(api_url)
    ws_scheme = "wss" if base.scheme == "https" else "ws"
    absolute_path = urljoin(f"{base.scheme}://{base.netloc}", ws_target)
    resolved = urlsplit(absolute_path)
    return urlunsplit((ws_scheme, resolved.netloc, resolved.path, resolved.query, resolved.fragment))


class RegisteredAgentSession(BaseModel):
    """Resolved agent registration data used by the runtime loop."""

    agent_id: str
    session_token: str
    session_token_expires_at: datetime
    heartbeat_interval_seconds: int
    websocket_url: str

    @classmethod
    def from_registration(
        cls,
        *,
        api_url: str,
        registration: AgentRegistrationResponse,
    ) -> RegisteredAgentSession:
        return cls(
            agent_id=registration.agent.id,
            session_token=registration.session_token,
            session_token_expires_at=registration.session_token_expires_at,
            heartbeat_interval_seconds=registration.config.heartbeat_interval_seconds,
            websocket_url=_resolve_websocket_url(
                api_url,
                registration.config.websocket_path,
            ),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        return self.session_token_expires_at <= reference


class JobDispatchMessage(BaseModel):
    """Job delivery message received from the control plane."""

    type: Literal["job_dispatch"]
    job_id: str
    job_type: JobType
    payload: str


class HeartbeatMessage(BaseModel):
    """Heartbeat sent to keep the agent session alive."""

    type: Literal["heartbeat"] = "heartbeat"


class JobStartedMessage(BaseModel):
    """Job state update sent before local execution starts."""

    type: Literal["job_started"] = "job_started"
    job_id: str


class JobResultMessage(BaseModel):
    """Successful job completion payload."""

    type: Literal["job_result"] = "job_result"
    job_id: str
    result: str


class JobFailedMessage(BaseModel):
    """Failed job completion payload."""

    type: Literal["job_failed"] = "job_failed"
    job_id: str
    error: str
