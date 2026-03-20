"""Slack WebClient wrapper.

Uses ``slack_sdk.WebClient`` (raw HTTP), NOT ``slack_bolt`` (surface framework).
Any layer may import this; surface-specific Bolt wiring stays in ``legion/slack/``.
"""

from __future__ import annotations

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from legion.core.exceptions import ExternalAPIError
from legion.core.slack.config import SlackConfig
from legion.core.slack.models import ConversationHistory, SlackMessage

logger = logging.getLogger(__name__)


class SlackClient:
    """Thin wrapper around ``slack_sdk.WebClient`` that raises ``ExternalAPIError``."""

    def __init__(self, config: SlackConfig) -> None:
        self._client = WebClient(token=config.bot_token.get_secret_value())

    # -- Channel lifecycle ---------------------------------------------------

    def create_channel(self, name: str) -> str:
        """Create a public channel and return its ID."""
        return self._api_call("conversations.create", name=name)["channel"]["id"]

    def archive_channel(self, channel_id: str) -> None:
        self._api_call("conversations.archive", channel=channel_id)

    def set_channel_topic(self, channel_id: str, topic: str) -> None:
        self._api_call("conversations.setTopic", channel=channel_id, topic=topic)

    def invite_users(self, channel_id: str, user_ids: list[str]) -> None:
        self._api_call(
            "conversations.invite",
            channel=channel_id,
            users=",".join(user_ids),
        )

    # -- Messaging -----------------------------------------------------------

    def post_message(
        self,
        channel_id: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
    ) -> str:
        """Post a message and return its ``ts``."""
        kwargs: dict[str, Any] = {"channel": channel_id, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        resp = self._api_call("chat.postMessage", **kwargs)
        return resp["ts"]

    def update_message(
        self,
        channel_id: str,
        ts: str,
        text: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"channel": channel_id, "ts": ts, "text": text}
        if blocks:
            kwargs["blocks"] = blocks
        if attachments:
            kwargs["attachments"] = attachments
        self._api_call("chat.update", **kwargs)

    def pin_message(self, channel_id: str, ts: str) -> None:
        self._api_call("pins.add", channel=channel_id, timestamp=ts)

    # -- History -------------------------------------------------------------

    def fetch_conversation_history(
        self, channel_id: str, *, limit: int = 100
    ) -> ConversationHistory:
        resp = self._api_call("conversations.history", channel=channel_id, limit=limit)
        messages = [SlackMessage(**m) for m in resp.get("messages", [])]
        return ConversationHistory(channel_id=channel_id, messages=messages)

    # -- Internal ------------------------------------------------------------

    def _api_call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """Dispatch a Slack API method, translating errors."""
        try:
            response = self._client.api_call(method, json=kwargs)
            return response.data  # type: ignore[return-value]
        except SlackApiError as exc:
            raise ExternalAPIError(
                f"Slack API error on {method}: {exc.response['error']}",
                service="slack",
                status_code=exc.response.status_code,
                retryable=exc.response.status_code >= 500,
            ) from exc
