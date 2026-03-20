"""Slack-specific incident state.

Per CONTRIBUTING.md: channel_id and dashboard_message_ts belong HERE,
not on the domain Incident model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class SlackIncidentState:
    """Maps a domain incident to its Slack channel artefacts."""

    __slots__ = ("incident_id", "channel_id", "dashboard_message_ts")

    def __init__(
        self,
        incident_id: str,
        channel_id: str,
        dashboard_message_ts: Optional[str] = None,
    ) -> None:
        self.incident_id = incident_id
        self.channel_id = channel_id
        self.dashboard_message_ts = dashboard_message_ts


class SlackIncidentIndex(ABC):
    """Bidirectional lookup between channel IDs and incident IDs."""

    @abstractmethod
    def register(self, state: SlackIncidentState) -> None: ...

    @abstractmethod
    def get_by_channel(self, channel_id: str) -> Optional[SlackIncidentState]: ...

    @abstractmethod
    def get_by_incident(self, incident_id: str) -> Optional[SlackIncidentState]: ...


class InMemorySlackIncidentIndex(SlackIncidentIndex):
    """In-memory implementation for tests and simple deployments."""

    def __init__(self) -> None:
        self._by_channel: dict[str, str] = {}
        self._by_incident: dict[str, SlackIncidentState] = {}

    def register(self, state: SlackIncidentState) -> None:
        self._by_channel[state.channel_id] = state.incident_id
        self._by_incident[state.incident_id] = state

    def get_by_channel(self, channel_id: str) -> Optional[SlackIncidentState]:
        incident_id = self._by_channel.get(channel_id)
        if incident_id is None:
            return None
        return self._by_incident.get(incident_id)

    def get_by_incident(self, incident_id: str) -> Optional[SlackIncidentState]:
        return self._by_incident.get(incident_id)
