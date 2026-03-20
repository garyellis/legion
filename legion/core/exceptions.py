"""Core-layer exceptions.

Source of truth: ERROR_CONTRACTS_draft.md §5.1
"""

from __future__ import annotations

from legion.plumbing.exceptions import LegionError


class CoreError(LegionError):
    """Base for all core-layer errors."""


class ExternalAPIError(CoreError):
    """An external API returned an error response."""

    _serializable_fields = ("message", "retryable", "service", "status_code")

    def __init__(
        self,
        message: str,
        *,
        service: str,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message, retryable=retryable)
        self.service = service
        self.status_code = status_code


class ResourceNotFoundError(CoreError):
    """A requested resource was not found in an external system."""

    _serializable_fields = ("message", "retryable", "resource_type", "resource_id")

    def __init__(self, message: str, *, resource_type: str, resource_id: str) -> None:
        super().__init__(message, retryable=False)
        self.resource_type = resource_type
        self.resource_id = resource_id


class AuthenticationError(CoreError):
    """Authentication with an external service failed."""

    def __init__(self, message: str, *, service: str) -> None:
        super().__init__(message, retryable=False)
        self.service = service


class ExternalTimeoutError(CoreError):
    """An external API call timed out."""

    _serializable_fields = ("message", "retryable", "service", "timeout_seconds")

    def __init__(self, message: str, *, service: str, timeout_seconds: float) -> None:
        super().__init__(message, retryable=True)
        self.service = service
        self.timeout_seconds = timeout_seconds
