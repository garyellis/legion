"""WebSocket protocol message models shared between agent runner and control plane."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from legion.domain.job import JobType


# --- Server-to-agent messages ---


class JobDispatchMessage(BaseModel):
    """Job delivery message sent from the control plane to an agent."""

    type: Literal["job_dispatch"]
    job_id: str
    job_type: JobType
    payload: str
    system_prompt: str = ""
    max_job_tokens: int = 32_768


# --- Agent-to-server messages ---


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


class JobProgressMessage(BaseModel):
    """Incremental progress update sent during job execution."""

    type: Literal["job_progress"] = "job_progress"
    job_id: str
    step: str
    detail: str = ""
    sequence: int


class MessageEmitMessage(BaseModel):
    """User-facing message emitted by the agent during a job."""

    type: Literal["message_emit"] = "message_emit"
    job_id: str
    message_type: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuditEventMessage(BaseModel):
    """Tool invocation audit record sent after each tool call."""

    type: Literal["audit_event"] = "audit_event"
    job_id: str
    tool_name: str
    tool_input: str
    tool_output: str
    duration_ms: int
    sequence: int
    error: str | None = None


# --- Discriminated union ---

AgentToServerMessage = Annotated[
    HeartbeatMessage
    | JobStartedMessage
    | JobResultMessage
    | JobFailedMessage
    | JobProgressMessage
    | MessageEmitMessage
    | AuditEventMessage,
    Field(discriminator="type"),
]
