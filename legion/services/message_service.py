"""Message service — persists and relays structured timeline entries."""

from __future__ import annotations

import logging
from typing import Callable

from legion.domain.message import Message
from legion.services.message_repository import MessageRepository

logger = logging.getLogger(__name__)

OnMessageCreated = Callable[[Message], None]


class MessageService:
    """Coordinates message persistence and notification.

    Surface-agnostic: signals creation through an optional callback so that
    Slack posting, streaming, etc. can be wired at the surface layer.
    """

    def __init__(
        self,
        message_repo: MessageRepository,
        *,
        on_message_created: OnMessageCreated | None = None,
    ) -> None:
        self.message_repo = message_repo
        self._on_created = on_message_created

    def emit(self, message: Message) -> Message:
        """Persist message and fire callback."""
        self.message_repo.save(message)
        logger.info("Message emitted: %s (session=%s)", message.id, message.session_id)

        if self._on_created:
            try:
                self._on_created(message)
            except Exception:
                logger.error(
                    "on_message_created callback failed for message %s (session=%s)",
                    message.id,
                    message.session_id,
                    exc_info=True,
                )

        return message

    def list_by_session(self, session_id: str) -> list[Message]:
        """Return all messages for a session, ordered by created_at."""
        return self.message_repo.list_by_session(session_id)

    def list_by_job(self, job_id: str) -> list[Message]:
        """Return all messages for a job, ordered by created_at."""
        return self.message_repo.list_by_job(job_id)
