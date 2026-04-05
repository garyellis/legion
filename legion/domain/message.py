"""Message domain model — structured timeline entries for sessions and jobs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


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


def _ensure_json_compatible(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_json_compatible(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} must use string keys")
            _ensure_json_compatible(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} must contain only JSON-compatible values")


class Message(BaseModel):
    """A structured timeline entry attached to a session and optionally a job."""

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
        _ensure_json_compatible(value, path="metadata")
        return value
