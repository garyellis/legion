"""Session transport-link repository protocol."""

from __future__ import annotations

from typing import Protocol


class SessionLinkRepository(Protocol):
    """Maps transport-specific thread identifiers to shared session IDs."""

    def get_session_id(self, channel_id: str, thread_ts: str) -> str | None: ...

    def save_link(self, session_id: str, channel_id: str, thread_ts: str) -> None: ...
