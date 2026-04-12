"""Behavior tests for Slack app_mention routing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from legion.domain.agent_group import AgentGroup
from legion.domain.channel_mapping import ChannelMapping, ChannelMode
from legion.domain.organization import Organization
from legion.domain.project import Project
from legion.plumbing.database import create_all, create_engine
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.session_repository import SQLiteSessionRepository
from legion.services.session_service import SessionService
from legion.slack.chat.handlers import handle_app_mention
from legion.slack.session.persistence import SQLiteSlackSessionLinkRepository


class _SayRecorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, text: str) -> None:
        self.messages.append(text)


def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


def _seed_chat_mapping(fleet_repo: SQLiteFleetRepository, *, channel_id: str, mode: ChannelMode) -> None:
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
            channel_id=channel_id,
            agent_group_id=agent_group.id,
            mode=mode,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )


def _session_scope():
    engine = _engine()
    fleet_repo = SQLiteFleetRepository(engine)
    session_repo = SQLiteSessionRepository(engine)
    session_link_repo = SQLiteSlackSessionLinkRepository(engine)
    session_service = SessionService(session_repo, fleet_repo, session_link_repo)
    return engine, fleet_repo, session_repo, session_link_repo, session_service


def test_app_mention_in_chat_channel_creates_and_reuses_session() -> None:
    _, fleet_repo, session_repo, session_link_repo, session_service = _session_scope()
    _seed_chat_mapping(fleet_repo, channel_id="C-CHAT", mode=ChannelMode.CHAT)
    say = _SayRecorder()
    event = {
        "user": "U123",
        "channel": "C-CHAT",
        "thread_ts": "1717.0001",
        "ts": "1717.0002",
    }

    asyncio.run(
        handle_app_mention(
            event,
            say,
            fleet_repo=fleet_repo,
            session_service=session_service,
        ),
    )
    asyncio.run(
        handle_app_mention(
            event,
            say,
            fleet_repo=fleet_repo,
            session_service=session_service,
        ),
    )

    session_id = session_link_repo.get_session_id("C-CHAT", "1717.0001")
    assert session_id is not None
    assert session_link_repo.get_session_id("C-CHAT", "1717.0002") is None
    assert session_repo.get_by_id(session_id) is not None
    assert len(session_repo.list_active()) == 1
    assert len(say.messages) == 2
    assert all("Hello <@U123>" in message for message in say.messages)


def test_app_mention_prefers_thread_timestamp_over_event_timestamp() -> None:
    _, fleet_repo, session_repo, session_link_repo, session_service = _session_scope()
    _seed_chat_mapping(fleet_repo, channel_id="C-CHAT", mode=ChannelMode.CHAT)
    say = _SayRecorder()

    asyncio.run(
        handle_app_mention(
            {"user": "U123", "channel": "C-CHAT", "thread_ts": "2222.0001", "ts": "1111.0001"},
            say,
            fleet_repo=fleet_repo,
            session_service=session_service,
        ),
    )

    assert session_link_repo.get_session_id("C-CHAT", "2222.0001") is not None
    assert session_link_repo.get_session_id("C-CHAT", "1111.0001") is None
    assert len(session_repo.list_active()) == 1


def test_app_mention_falls_back_to_event_timestamp_when_thread_missing() -> None:
    _, fleet_repo, session_repo, session_link_repo, session_service = _session_scope()
    _seed_chat_mapping(fleet_repo, channel_id="C-CHAT", mode=ChannelMode.CHAT)
    say = _SayRecorder()

    asyncio.run(
        handle_app_mention(
            {"user": "U123", "channel": "C-CHAT", "ts": "1111.0001"},
            say,
            fleet_repo=fleet_repo,
            session_service=session_service,
        ),
    )

    assert session_link_repo.get_session_id("C-CHAT", "1111.0001") is not None
    assert len(session_repo.list_active()) == 1


def test_app_mention_does_not_create_session_for_unmapped_or_non_chat_channel() -> None:
    for mode in (None, ChannelMode.ALERT):
        _, fleet_repo, session_repo, session_link_repo, session_service = _session_scope()
        if mode is not None:
            _seed_chat_mapping(fleet_repo, channel_id="C-OTHER", mode=mode)
            channel_id = "C-OTHER"
        else:
            channel_id = "C-OTHER"
        say = _SayRecorder()

        asyncio.run(
            handle_app_mention(
                {"user": "U123", "channel": channel_id, "ts": "1111.0001"},
                say,
                fleet_repo=fleet_repo,
                session_service=session_service,
            ),
        )

        assert session_link_repo.get_session_id(channel_id, "1111.0001") is None
        assert len(session_repo.list_active()) == 0
        assert len(say.messages) == 1
