"""Behavior tests for Slack incident routing."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from legion.domain.agent_group import AgentGroup
from legion.domain.channel_mapping import ChannelMapping, ChannelMode
from legion.domain.incident import IncidentSeverity
from legion.domain.organization import Organization
from legion.domain.project import Project
from legion.plumbing.database import create_all, create_engine
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.incident_service import IncidentService
from legion.services.repository import SQLiteIncidentRepository
from legion.slack.incident.handlers import (
    handle_incident_command,
    handle_incident_submission,
)
from legion.slack.incident.models import InMemorySlackIncidentIndex
from legion.slack.session.persistence import SQLiteSlackSessionLinkRepository
from legion.services.session_repository import SQLiteSessionRepository


def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


def _seed_origin_mapping(
    fleet_repo: SQLiteFleetRepository,
    *,
    origin_channel_id: str,
    mode: ChannelMode = ChannelMode.ALERT,
) -> None:
    org = Organization(id="org-1", name="Org 1", slug="org-1")
    project = Project(id="proj-1", org_id=org.id, name="Project 1", slug="proj-1")
    agent_group = AgentGroup(
        id="ag-1",
        org_id=org.id,
        project_id=project.id,
        name="Agent Group 1",
        slug="ag-1",
        environment="dev",
        provider="aks",
    )
    fleet_repo.save_org(org)
    fleet_repo.save_project(project)
    fleet_repo.save_agent_group(agent_group)
    fleet_repo.save_channel_mapping(
        ChannelMapping(
            org_id=org.id,
            channel_id=origin_channel_id,
            agent_group_id=agent_group.id,
            mode=mode,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )


class _IncidentClientStub:
    def __init__(self, *, channel_id: str = "C-INC-001", dashboard_ts: str = "1717.0001") -> None:
        self.channel_id = channel_id
        self.dashboard_ts = dashboard_ts
        self.created_channels: list[str] = []
        self.invites: list[tuple[str, list[str]]] = []
        self.topics: list[tuple[str, str]] = []
        self.posted_messages: list[tuple[str, str]] = []
        self.pinned_messages: list[tuple[str, str]] = []
        self.chat_messages: list[dict[str, str]] = []
        self.views: list[dict[str, object]] = []

    def create_channel(self, name: str) -> str:
        self.created_channels.append(name)
        return self.channel_id

    def invite_users(self, channel_id: str, user_ids: list[str]) -> None:
        self.invites.append((channel_id, user_ids))

    def set_channel_topic(self, channel_id: str, topic: str) -> None:
        self.topics.append((channel_id, topic))

    def post_message(self, channel_id: str, text: str, blocks: list[dict[str, object]] | None = None) -> str:
        self.posted_messages.append((channel_id, text))
        return self.dashboard_ts

    def pin_message(self, channel_id: str, ts: str) -> None:
        self.pinned_messages.append((channel_id, ts))

    async def chat_postMessage(self, *, channel: str, text: str) -> None:
        self.chat_messages.append({"channel": channel, "text": text})

    async def views_open(self, *, trigger_id: str, view: dict[str, object]) -> None:
        self.views.append({"trigger_id": trigger_id, "view": view})


class _AckRecorder:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1


def test_incident_command_carries_origin_channel_metadata() -> None:
    ack = _AckRecorder()
    client = _IncidentClientStub()

    asyncio.run(
        handle_incident_command(
            ack,
            {"channel_id": "C-ORIGIN", "trigger_id": "T-123"},
            client,
        ),
    )

    assert ack.calls == 1
    assert len(client.views) == 1
    view = client.views[0]["view"]
    assert json.loads(view["private_metadata"]) == {"origin_channel_id": "C-ORIGIN"}


def test_incident_submission_binds_session_when_origin_channel_is_mapped() -> None:
    engine = _engine()
    fleet_repo = SQLiteFleetRepository(engine)
    session_repo = SQLiteSessionRepository(engine)
    incident_repo = SQLiteIncidentRepository(engine)
    incident_service = IncidentService(incident_repo)
    slack_index = InMemorySlackIncidentIndex()
    session_link_repo = SQLiteSlackSessionLinkRepository(engine)
    _seed_origin_mapping(fleet_repo, origin_channel_id="C-ORIGIN", mode=ChannelMode.ALERT)
    client = _IncidentClientStub()
    ack = _AckRecorder()
    view = {
        "private_metadata": json.dumps({"origin_channel_id": "C-ORIGIN"}),
        "state": {
            "values": {
                "title_block": {"title_input": {"value": "Database outage"}},
                "desc_block": {"desc_input": {"value": "Primary DB is down"}},
                "severity_block": {
                    "severity_input": {"selected_option": {"value": IncidentSeverity.SEV1.value}}
                },
                "interval_block": {
                    "interval_input": {"selected_option": {"value": "15"}}
                },
            }
        },
    }

    asyncio.run(
        handle_incident_submission(
            ack,
            {"user": {"id": "U123"}},
            client,
            view,
            incident_service=incident_service,
            slack_client=client,
            slack_index=slack_index,
            session_link_repo=session_link_repo,
        ),
    )

    assert ack.calls == 1
    assert len(client.chat_messages) == 1
    incident = incident_service.get_active_incidents()[0]
    state = slack_index.get_by_incident(incident.id)
    assert state is not None
    assert state.channel_id == client.channel_id
    assert state.dashboard_message_ts == client.dashboard_ts

    session_id = session_link_repo.get_session_id(client.channel_id, client.dashboard_ts)
    assert session_id is not None
    session = session_repo.get_by_id(session_id)
    assert session is not None
    assert session.org_id == "org-1"
    assert session.agent_group_id == "ag-1"


def test_incident_submission_skips_session_binding_without_origin_mapping() -> None:
    engine = _engine()
    incident_repo = SQLiteIncidentRepository(engine)
    incident_service = IncidentService(incident_repo)
    slack_index = InMemorySlackIncidentIndex()
    session_link_repo = SQLiteSlackSessionLinkRepository(engine)
    client = _IncidentClientStub()
    ack = _AckRecorder()
    view = {
        "private_metadata": json.dumps({"origin_channel_id": "C-MISSING"}),
        "state": {
            "values": {
                "title_block": {"title_input": {"value": "Cache outage"}},
                "desc_block": {"desc_input": {"value": "Redis is unavailable"}},
                "severity_block": {
                    "severity_input": {"selected_option": {"value": IncidentSeverity.SEV2.value}}
                },
                "interval_block": {
                    "interval_input": {"selected_option": {"value": "20"}}
                },
            }
        },
    }

    asyncio.run(
        handle_incident_submission(
            ack,
            {"user": {"id": "U123"}},
            client,
            view,
            incident_service=incident_service,
            slack_client=client,
            slack_index=slack_index,
            session_link_repo=session_link_repo,
        ),
    )

    assert ack.calls == 1
    assert len(client.chat_messages) == 1
    incident = incident_service.get_active_incidents()[0]
    state = slack_index.get_by_incident(incident.id)
    assert state is not None
    assert session_link_repo.get_session_id(client.channel_id, client.dashboard_ts) is None
