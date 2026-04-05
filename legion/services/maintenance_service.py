"""Maintenance service — scheduled data retention and cleanup."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from legion.services.audit_event_repository import AuditEventRepository
from legion.services.message_repository import MessageRepository

logger = logging.getLogger(__name__)

MIN_RETENTION_DAYS = 30


class MaintenanceService:
    """Coordinates scheduled data retention and cleanup.

    Repositories must implement purge_before(cutoff) -> int.
    Scheduling is handled by the caller (e.g., the API lifespan scheduler).

    Note: if multiple application replicas run maintenance concurrently,
    purge operations are idempotent but logged counts should not be summed
    across replicas.  For accurate metrics, run maintenance on a single
    replica via leader election or a dedicated scheduler.
    """

    def __init__(
        self,
        audit_repo: AuditEventRepository,
        message_repo: MessageRepository,
        *,
        audit_retention_days: int = 90,
        message_retention_days: int = 180,
    ) -> None:
        if audit_retention_days < MIN_RETENTION_DAYS:
            raise ValueError(
                f"audit_retention_days must be >= {MIN_RETENTION_DAYS}, got {audit_retention_days}"
            )
        if message_retention_days < MIN_RETENTION_DAYS:
            raise ValueError(
                f"message_retention_days must be >= {MIN_RETENTION_DAYS}, got {message_retention_days}"
            )
        self._audit_repo = audit_repo
        self._message_repo = message_repo
        self._audit_retention_days = audit_retention_days
        self._message_retention_days = message_retention_days

    def run_audit_purge(self) -> int:
        """Purge audit events older than the configured retention period.

        Returns the number of events deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._audit_retention_days)
        count = self._audit_repo.purge_before(cutoff)
        logger.info(
            "Audit purge complete: deleted %d events older than %s (%d day retention)",
            count, cutoff.isoformat(), self._audit_retention_days,
        )
        return count

    def run_message_purge(self) -> int:
        """Purge messages older than the configured retention period.

        Returns the number of messages deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._message_retention_days)
        count = self._message_repo.purge_before(cutoff)
        logger.info(
            "Message purge complete: deleted %d messages older than %s (%d day retention)",
            count, cutoff.isoformat(), self._message_retention_days,
        )
        return count

    def run_all(self) -> dict[str, int]:
        """Run all maintenance tasks. Returns counts by task name."""
        return {
            "audit_events_purged": self.run_audit_purge(),
            "messages_purged": self.run_message_purge(),
        }
