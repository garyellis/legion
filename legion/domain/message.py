"""Message domain model — structured timeline entries for sessions and jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from legion.plumbing.validation import ensure_json_compatible


class AuthorType(str, Enum):
    HUMAN = "HUMAN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class MessageType(str, Enum):
    HUMAN_MESSAGE = "HUMAN_MESSAGE"
    AGENT_FINDING = "AGENT_FINDING"
    AGENT_PROPOSAL = "AGENT_PROPOSAL"
    TOOL_SUMMARY = "TOOL_SUMMARY"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    APPROVAL_RESPONSE = "APPROVAL_RESPONSE"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    STATUS_UPDATE = "STATUS_UPDATE"


class Message(BaseModel):
    """Human-oriented timeline entry within a session.

    Messages represent information a person would see: findings, proposals,
    status updates, approval requests, and system notifications.  They carry
    a natural-language content string and optional structured metadata, but
    never raw tool I/O.

    Messages are addressed to the session timeline and may span multiple jobs
    or have no job at all (system events).  Emit a Message when an agent
    produces a conclusion or needs human attention.  Do *not* use Message as a
    substitute for AuditEvent — tool-level detail belongs in the audit trail.
    """

    model_config = {"validate_assignment": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    session_id: str
    author_id: str
    author_type: AuthorType
    message_type: MessageType
    content: str
    job_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        ensure_json_compatible(value, path="metadata")
        return value
