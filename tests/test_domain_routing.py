"""Tests for routing domain models: ChannelMapping, FilterRule, PromptConfig, Session."""

from legion.domain.channel_mapping import ChannelMapping, ChannelMode
from legion.domain.filter_rule import FilterAction, FilterRule
from legion.domain.prompt_config import PromptConfig
from legion.domain.session import Session, SessionStatus


class TestChannelMapping:
    def test_creation_defaults(self):
        m = ChannelMapping(
            org_id="org-1", channel_id="C123", agent_group_id="ag-1",
        )
        assert m.id
        assert m.mode == ChannelMode.ALERT
        assert m.created_at.tzinfo is not None

    def test_chat_mode(self):
        m = ChannelMapping(
            org_id="org-1", channel_id="C123",
            agent_group_id="ag-1", mode=ChannelMode.CHAT,
        )
        assert m.mode == ChannelMode.CHAT


class TestFilterRule:
    def test_creation_defaults(self):
        r = FilterRule(channel_mapping_id="cm-1", pattern="CRITICAL|ERROR")
        assert r.id
        assert r.action == FilterAction.TRIAGE
        assert r.priority == 0

    def test_ignore_action(self):
        r = FilterRule(
            channel_mapping_id="cm-1", pattern="heartbeat",
            action=FilterAction.IGNORE, priority=10,
        )
        assert r.action == FilterAction.IGNORE
        assert r.priority == 10


class TestPromptConfig:
    def test_creation_defaults(self):
        pc = PromptConfig(agent_group_id="ag-1")
        assert pc.id
        assert pc.system_prompt == ""
        assert pc.stack_manifest == ""
        assert pc.persona == ""

    def test_with_values(self):
        pc = PromptConfig(
            agent_group_id="ag-1",
            system_prompt="You are a K8s expert",
            stack_manifest="App → Redis → PG",
            persona="PostgreSQL Expert",
        )
        assert pc.system_prompt == "You are a K8s expert"
        assert pc.stack_manifest == "App → Redis → PG"


class TestSession:
    def test_creation_defaults(self):
        s = Session(org_id="org-1", agent_group_id="ag-1")
        assert s.id
        assert s.status == SessionStatus.ACTIVE
        assert s.agent_id is None
        assert s.slack_channel_id is None
        assert s.slack_thread_ts is None

    def test_pin_agent(self):
        s = Session(org_id="org-1", agent_group_id="ag-1")
        s.pin_agent("agent-1")
        assert s.agent_id == "agent-1"

    def test_touch_updates_last_activity(self):
        s = Session(org_id="org-1", agent_group_id="ag-1")
        original = s.last_activity
        s.touch()
        assert s.last_activity >= original

    def test_close(self):
        s = Session(org_id="org-1", agent_group_id="ag-1")
        s.close()
        assert s.status == SessionStatus.CLOSED
