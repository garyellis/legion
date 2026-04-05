"""Base exception hierarchy for the legion project.

Source of truth: ERROR_CONTRACTS_draft.md §4
"""

from __future__ import annotations

from typing import Any


class LegionError(Exception):
    """Root of all legion exceptions.

    Attributes:
        message: Human-readable description.
        retryable: Hint for callers — True means a retry *might* succeed.
    """

    retryable: bool = False
    _serializable_fields: tuple[str, ...] = ("message", "retryable")

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.message = message
        if retryable is not None:
            self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict containing only declared serializable fields."""
        data: dict[str, Any] = {"type": type(self).__name__}
        for field in self._serializable_fields:
            data[field] = getattr(self, field, None)
        return data

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{f}={getattr(self, f)!r}" for f in self._serializable_fields
        )
        return f"{type(self).__name__}({fields})"


class CoreError(LegionError):
    """Base for all core/ layer exceptions (infrastructure clients)."""


class DatabaseSchemaError(LegionError):
    """Base for migration and schema-state failures."""


class DatabaseSchemaOutOfDateError(DatabaseSchemaError):
    """Raised when a database is behind the repo's Alembic head."""
