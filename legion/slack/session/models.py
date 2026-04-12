"""Slack-owned session link models."""

from __future__ import annotations

from pydantic import BaseModel


class SlackSessionLink(BaseModel):
    """Link a Slack conversation thread to an internal session."""

    channel_id: str
    thread_ts: str
    session_id: str

