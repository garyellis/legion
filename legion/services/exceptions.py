"""Service-layer exceptions.

Source of truth: ERROR_CONTRACTS_draft.md §5.3
"""

from __future__ import annotations

from legion.plumbing.exceptions import LegionError


class ServiceError(LegionError):
    """Base for all service-layer errors."""


class IncidentCreationError(ServiceError):
    """Failed to create an incident."""


class OrchestrationError(ServiceError):
    """A multi-step service workflow failed partway through."""

    _serializable_fields = ("message", "retryable", "step")

    def __init__(self, message: str, *, step: str, retryable: bool = False) -> None:
        super().__init__(message, retryable=retryable)
        self.step = step


class DuplicateError(ServiceError):
    """Attempted to create a resource that already exists."""


class DispatchError(ServiceError):
    """Job dispatch failed."""


class AgentNotFoundError(ServiceError):
    """Referenced agent does not exist."""


class SessionError(ServiceError):
    """Session lifecycle error."""


class FilterError(ServiceError):
    """Filter rule evaluation failed."""
