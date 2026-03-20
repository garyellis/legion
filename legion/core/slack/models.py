"""Pydantic models for Slack API data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlackMessage(BaseModel):
    """A single Slack message."""

    user: str = ""
    text: str = ""
    ts: str = ""
    thread_ts: str | None = None


class ConversationHistory(BaseModel):
    """Result of a conversations.history API call."""

    channel_id: str
    messages: list[SlackMessage] = Field(default_factory=list)
