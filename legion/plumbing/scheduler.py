"""Generic APScheduler wrapper for background jobs.

Adapted from references/incident-commander-bot/core/scheduler.py.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """Thin wrapper around APScheduler's BackgroundScheduler.

    Runs in a separate thread so it doesn't conflict with async event loops.
    """

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._is_running = False

    def add_job(
        self,
        func: Callable[..., Any],
        interval_seconds: int,
        args: Sequence[Any] | None = None,
        id: str | None = None,
    ) -> None:
        """Register a repeating job."""
        self._scheduler.add_job(
            func,
            trigger=IntervalTrigger(seconds=interval_seconds),
            args=args,
            id=id,
            replace_existing=True,
        )
        logger.info("Job added: %s every %ds", id or func.__name__, interval_seconds)

    def start(self) -> None:
        if not self._is_running:
            self._scheduler.start()
            self._is_running = True
            logger.info("Scheduler started.")

    def shutdown(self) -> None:
        if self._is_running:
            self._scheduler.shutdown()
            self._is_running = False
            logger.info("Scheduler stopped.")
