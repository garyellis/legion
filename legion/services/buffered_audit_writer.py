"""Buffered audit event writer — decouples agent hot path from DB I/O."""
from __future__ import annotations

import atexit
import logging
import threading
from collections import deque

from legion.domain.audit_event import AuditEvent
from legion.services.audit_event_repository import AuditEventRepository

logger = logging.getLogger(__name__)


class BufferedAuditWriter:
    """Accumulates audit events and flushes in batches.

    Thread-safe. Flushes when count threshold is reached, on a timer,
    or when explicitly requested.

    Callers should call ``close()`` explicitly for deterministic shutdown,
    but an ``atexit`` handler is registered as a safety net to flush any
    remaining events when the interpreter exits.
    """

    def __init__(
        self,
        repo: AuditEventRepository,
        *,
        max_batch_size: int = 50,
        flush_interval_seconds: float = 2.0,
        max_flush_retries: int = 2,
    ) -> None:
        self._repo = repo
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval_seconds
        self._buffer: deque[AuditEvent] = deque()
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._closed = False
        self._max_flush_retries = max_flush_retries
        self._retry_count = 0
        self._dropped_count = 0
        atexit.register(self.close)

    def append(self, event: AuditEvent) -> None:
        """Add an event to the buffer. Flushes if count threshold is reached."""
        with self._lock:
            if self._closed:
                logger.warning("BufferedAuditWriter is closed, dropping event %s", event.id)
                return
            self._buffer.append(event)
            if len(self._buffer) >= self._max_batch_size:
                self._flush_locked()
            elif self._timer is None:
                self._schedule_flush()

    def flush(self) -> None:
        """Explicitly flush all buffered events to the repository."""
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        """Flush remaining events and stop accepting new ones."""
        with self._lock:
            self._closed = True
            self._flush_locked()
        atexit.unregister(self.close)

    def _schedule_flush(self) -> None:
        """Schedule a timer-based flush. Must be called while holding self._lock."""
        self._timer = threading.Timer(self._flush_interval, self._timer_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timer_flush(self) -> None:
        """Timer callback — acquires lock and flushes."""
        with self._lock:
            self._timer = None
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Flush buffer to repository. Must be called while holding self._lock."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()
        try:
            self._repo.save_batch(batch)
            logger.debug("Flushed %d audit events", len(batch))
            self._retry_count = 0
        except Exception:
            if self._retry_count < self._max_flush_retries:
                self._retry_count += 1
                # Re-buffer for next flush attempt
                for event in reversed(batch):
                    self._buffer.appendleft(event)
                logger.warning(
                    "Flush failed, re-buffered %d events (retry %d/%d)",
                    len(batch), self._retry_count, self._max_flush_retries,
                    exc_info=True,
                )
                if self._timer is None:
                    self._schedule_flush()
            else:
                self._dropped_count += len(batch)
                self._retry_count = 0
                logger.error(
                    "Flush failed after %d retries, dropped %d audit events (total dropped: %d)",
                    self._max_flush_retries, len(batch), self._dropped_count,
                    exc_info=True,
                )

    @property
    def pending_count(self) -> int:
        """Number of events waiting to be flushed (for testing/monitoring)."""
        with self._lock:
            return len(self._buffer)

    @property
    def dropped_count(self) -> int:
        """Total number of events dropped due to persistent flush failures."""
        with self._lock:
            return self._dropped_count
