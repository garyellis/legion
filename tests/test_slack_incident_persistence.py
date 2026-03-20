"""Contract tests for SlackIncidentIndex implementations."""

import pytest

from legion.plumbing.database import create_all, create_engine
from legion.slack.incident.models import InMemorySlackIncidentIndex, SlackIncidentState
from legion.slack.incident.persistence import SQLiteSlackIncidentIndex


@pytest.fixture(params=["memory", "sqlite"])
def index(request):
    if request.param == "memory":
        return InMemorySlackIncidentIndex()
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteSlackIncidentIndex(engine)


class TestSlackIncidentIndexContract:
    def test_register_and_get_by_channel(self, index):
        state = SlackIncidentState("inc-1", "C001", "ts-1")
        index.register(state)
        found = index.get_by_channel("C001")
        assert found is not None
        assert found.incident_id == "inc-1"
        assert found.channel_id == "C001"
        assert found.dashboard_message_ts == "ts-1"

    def test_register_and_get_by_incident(self, index):
        state = SlackIncidentState("inc-2", "C002")
        index.register(state)
        found = index.get_by_incident("inc-2")
        assert found is not None
        assert found.incident_id == "inc-2"
        assert found.channel_id == "C002"
        assert found.dashboard_message_ts is None

    def test_get_nonexistent_channel(self, index):
        assert index.get_by_channel("nope") is None

    def test_get_nonexistent_incident(self, index):
        assert index.get_by_incident("nope") is None

    def test_overwrite_existing(self, index):
        state1 = SlackIncidentState("inc-3", "C003", "ts-old")
        index.register(state1)

        state2 = SlackIncidentState("inc-3", "C003-new", "ts-new")
        index.register(state2)

        found = index.get_by_incident("inc-3")
        assert found is not None
        assert found.channel_id == "C003-new"
        assert found.dashboard_message_ts == "ts-new"

        assert index.get_by_channel("C003-new") is not None
