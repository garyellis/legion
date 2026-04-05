"""Audit event domain model — immutable record of agent actions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from legion.plumbing.validation import ensure_json_compatible

MAX_PAYLOAD_BYTES = 65_536  # 64 KiB per field


def _truncate_if_oversized(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    """Replace oversized dicts with a truncation sentinel."""
    serialized = json.dumps(value)
    byte_length = len(serialized.encode("utf-8"))
    if byte_length <= MAX_PAYLOAD_BYTES:
        return value
    # Byte-safe preview: take first 512 bytes, decode lossily to avoid mid-character cuts
    preview = serialized.encode("utf-8")[:512].decode("utf-8", errors="ignore")
    return {
        "_truncated": True,
        "_original_bytes": byte_length,
        "_preview": preview,
    }


class AuditAction(str, Enum):
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    LLM_DECISION = "LLM_DECISION"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED = "APPROVAL_DENIED"


class AuditEvent(BaseModel):
    """Machine-oriented record of a discrete agent action.

    AuditEvents capture every tool call, LLM decision, and approval state
    change during job execution.  They carry full technical detail (tool name,
    input arguments, raw output, duration) for post-hoc debugging, compliance
    auditing, and performance analysis.

    AuditEvents are write-once, never shown directly to end users, and always
    scoped to a specific job and agent.  Emit an AuditEvent for every tool
    invocation and LLM decision.  Do *not* also emit a Message for the same
    action unless the result must appear in the human-facing session timeline.
    """

    model_config = {"frozen": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    agent_id: str
    session_id: str
    org_id: str
    action: AuditAction
    tool_name: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("input")
    @classmethod
    def _validate_input(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            ensure_json_compatible(value, path="input")
            value = _truncate_if_oversized(value, field_name="input")
        return value

    @field_validator("output")
    @classmethod
    def _validate_output(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None:
            ensure_json_compatible(value, path="output")
            value = _truncate_if_oversized(value, field_name="output")
        return value
