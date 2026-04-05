"""Audit event service — fire-and-forget persistence wrapper."""

from __future__ import annotations

import logging
import os

from legion.domain.audit_event import AuditEvent
from legion.services.audit_event_repository import AuditEventRepository
from legion.services.buffered_audit_writer import BufferedAuditWriter

logger = logging.getLogger(__name__)


class AuditService:
    """Thin wrapper around AuditEventRepository.

    Ensures audit persistence never interrupts the caller's hot path.
    All exceptions from the repository are caught, logged, and suppressed.

    When buffered=True (default), events are accumulated in memory and
    flushed in batches. Call flush() at job boundaries and close() on
    shutdown to ensure all events are persisted.
    """

    def __init__(
        self,
        repo: AuditEventRepository,
        *,
        buffered: bool | None = None,
        max_batch_size: int = 50,
        flush_interval_seconds: float = 2.0,
    ) -> None:
        self._repo = repo
        if buffered is None:
            buffered = os.environ.get("LEGION_AUDIT_BUFFERED", "true").lower() != "false"
        self._writer: BufferedAuditWriter | None = None
        if buffered:
            self._writer = BufferedAuditWriter(
                repo,
                max_batch_size=max_batch_size,
                flush_interval_seconds=flush_interval_seconds,
            )

    def emit(self, event: AuditEvent) -> None:
        """Persist an audit event. Must not raise on failure — log and continue."""
        try:
            if self._writer is not None:
                self._writer.append(event)
            else:
                self._repo.save(event)
            logger.debug(
                "Audit event recorded: %s action=%s job=%s",
                event.id, event.action.value, event.job_id,
            )
        except Exception:
            logger.error(
                "Failed to record audit event: %s action=%s job=%s",
                event.id, event.action.value, event.job_id,
                exc_info=True,
            )

    def flush(self) -> None:
        """Flush buffered events to the repository. Call at job boundaries."""
        if self._writer is not None:
            self._writer.flush()

    def close(self) -> None:
        """Flush and stop accepting events. Call on shutdown."""
        if self._writer is not None:
            self._writer.close()
