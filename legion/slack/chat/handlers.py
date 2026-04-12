"""Slack chat routing for session-bearing app_mention events."""

from __future__ import annotations

import logging
from typing import Any

from legion.domain.channel_mapping import ChannelMode
from legion.services.fleet_repository import FleetRepository
from legion.services.session_service import SessionService

logger = logging.getLogger(__name__)


def _thread_timestamp(event: dict[str, Any]) -> str | None:
    """Return the conversation thread timestamp Slack should key sessions to."""
    thread_ts = event.get("thread_ts")
    if thread_ts:
        return str(thread_ts)

    ts = event.get("ts")
    if ts:
        return str(ts)

    return None


async def handle_app_mention(
    event: dict[str, Any],
    say: Any,
    *,
    fleet_repo: FleetRepository,
    session_service: SessionService,
) -> None:
    """Create or reuse a chat session for mapped ``app_mention`` events."""
    user_id = event.get("user")
    channel_id = event.get("channel")
    thread_ts = _thread_timestamp(event)

    if user_id is None or channel_id is None:
        logger.warning("Ignoring app_mention without user/channel: %s", event)
        return

    if thread_ts is None:
        logger.warning("Ignoring app_mention without thread timestamp: %s", event)
    else:
        mapping = fleet_repo.get_channel_mapping_by_channel(str(channel_id))
        if mapping is not None and mapping.mode == ChannelMode.CHAT:
            try:
                session_service.get_or_create(
                    mapping.org_id,
                    mapping.agent_group_id,
                    str(channel_id),
                    thread_ts,
                )
            except Exception:
                logger.exception(
                    "Failed to create or reuse chat session for channel %s",
                    channel_id,
                )

    await say(
        f"Hello <@{user_id}>! Try `/incident` to declare an incident."
    )


def register_chat_handlers(
    app: Any,
    *,
    fleet_repo: FleetRepository,
    session_service: SessionService,
) -> None:
    """Register Slack chat routing handlers on a Bolt app."""

    @app.event("app_mention")
    async def _handle_app_mention(event: dict[str, Any], say: Any) -> None:
        await handle_app_mention(
            event,
            say,
            fleet_repo=fleet_repo,
            session_service=session_service,
        )
