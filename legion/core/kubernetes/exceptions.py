"""Kubernetes-specific core exceptions."""

from __future__ import annotations

from legion.core.exceptions import CoreError


class KubernetesConfigError(CoreError):
    """Raised when Kubernetes client configuration cannot be loaded."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class KubernetesConnectionError(CoreError):
    """Raised when Legion cannot reach the Kubernetes API."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class KubernetesAPIError(CoreError):
    """Raised for unexpected Kubernetes API failures."""

    _serializable_fields: tuple[str, ...] = ("message", "retryable", "status_code")

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, retryable=False)
        self.status_code = status_code
