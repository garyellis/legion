"""Logging setup for legion surfaces.

Source of truth: LOGGING_draft.md §3

Each surface calls ``setup_logging()`` once at startup to configure the root
logger for its specific output routing.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import TextIO


class LogOutput(str, Enum):
    STDOUT = "stdout"
    STDERR = "stderr"


class LogFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


class _JsonFormatter(logging.Formatter):
    """Emit structured JSON log lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Merge any extra fields set via logging.info("msg", extra={...})
        for key in ("alert_id", "incident_id", "duration_ms", "verdict"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def setup_logging(
    *,
    level: str = "INFO",
    output: LogOutput = LogOutput.STDOUT,
    fmt: LogFormat = LogFormat.TEXT,
    quiet_loggers: list[str] | None = None,
) -> None:
    """Configure the root logger for a legion surface.

    Args:
        level: Root log level name (DEBUG, INFO, WARNING, ERROR).
        output: Where to send logs — stdout or stderr.
        fmt: Log line format — text or JSON.
        quiet_loggers: Logger names to suppress to WARNING (e.g. SDK loggers).
    """
    stream: TextIO = sys.stdout if output == LogOutput.STDOUT else sys.stderr

    handler = logging.StreamHandler(stream)
    if fmt == LogFormat.JSON:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for name in quiet_loggers or []:
        logging.getLogger(name).setLevel(logging.WARNING)
