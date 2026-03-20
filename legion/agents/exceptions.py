"""Agent-layer exceptions."""

from __future__ import annotations

from legion.plumbing.exceptions import LegionError


class AgentError(LegionError):
    """Base for all agent-layer errors."""


class LLMError(AgentError):
    """An LLM call failed."""

    _serializable_fields = ("message", "retryable", "model")

    def __init__(self, message: str, *, model: str, retryable: bool = True) -> None:
        super().__init__(message, retryable=retryable)
        self.model = model
