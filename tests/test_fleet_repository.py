"""Tests for FleetRepository contract (InMemory + SQLite)."""

import pytest

from legion.domain.agent import Agent, AgentStatus
from legion.domain.channel_mapping import ChannelMapping, ChannelMode
from legion.domain.cluster_group import ClusterGroup
from legion.domain.filter_rule import FilterAction, FilterRule
from legion.domain.organization import Organization
from legion.domain.prompt_config import PromptConfig
from legion.plumbing.database import create_all, create_engine
from legion.services.fleet_repository import (
    InMemoryFleetRepository,
    SQLiteFleetRepository,
)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request):
    if request.param == "memory":
        return InMemoryFleetRepository()
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteFleetRepository(engine)


class TestOrganizationContract:
    def test_save_and_get(self, repo):
        org = Organization(name="Acme", slug="acme")
        repo.save_org(org)
        loaded = repo.get_org(org.id)
        assert loaded is not None
        assert loaded.name == "Acme"
        assert loaded.slug == "acme"

    def test_list_orgs(self, repo):
        repo.save_org(Organization(name="A", slug="a"))
        repo.save_org(Organization(name="B", slug="b"))
        assert len(repo.list_orgs()) == 2

    def test_get_nonexistent(self, repo):
        assert repo.get_org("nope") is None

    def test_delete(self, repo):
        org = Organization(name="X", slug="x")
        repo.save_org(org)
        assert repo.delete_org(org.id) is True
        assert repo.get_org(org.id) is None
        assert repo.delete_org(org.id) is False


class TestClusterGroupContract:
    def test_save_and_get(self, repo):
        cg = ClusterGroup(
            org_id="org-1", name="US West", slug="us-west",
            environment="prod", provider="eks",
        )
        repo.save_cluster_group(cg)
        loaded = repo.get_cluster_group(cg.id)
        assert loaded is not None
        assert loaded.name == "US West"
        assert loaded.environment == "prod"

    def test_list_by_org(self, repo):
        cg1 = ClusterGroup(
            org_id="org-1", name="A", slug="a",
            environment="dev", provider="aks",
        )
        cg2 = ClusterGroup(
            org_id="org-1", name="B", slug="b",
            environment="staging", provider="gke",
        )
        cg3 = ClusterGroup(
            org_id="org-2", name="C", slug="c",
            environment="prod", provider="eks",
        )
        repo.save_cluster_group(cg1)
        repo.save_cluster_group(cg2)
        repo.save_cluster_group(cg3)
        result = repo.list_cluster_groups("org-1")
        assert len(result) == 2

    def test_delete(self, repo):
        cg = ClusterGroup(
            org_id="org-1", name="X", slug="x",
            environment="dev", provider="aks",
        )
        repo.save_cluster_group(cg)
        assert repo.delete_cluster_group(cg.id) is True
        assert repo.get_cluster_group(cg.id) is None


class TestAgentContract:
    def test_save_and_get(self, repo):
        agent = Agent(
            cluster_group_id="cg-1", name="agent-01",
            capabilities=["k8s", "logs"],
        )
        repo.save_agent(agent)
        loaded = repo.get_agent(agent.id)
        assert loaded is not None
        assert loaded.name == "agent-01"
        assert loaded.capabilities == ["k8s", "logs"]

    def test_list_by_cluster(self, repo):
        a1 = Agent(cluster_group_id="cg-1", name="a1")
        a2 = Agent(cluster_group_id="cg-1", name="a2")
        a3 = Agent(cluster_group_id="cg-2", name="a3")
        repo.save_agent(a1)
        repo.save_agent(a2)
        repo.save_agent(a3)
        assert len(repo.list_agents("cg-1")) == 2

    def test_list_idle_filters(self, repo):
        idle = Agent(cluster_group_id="cg-1", name="idle")
        idle.go_idle()
        busy = Agent(cluster_group_id="cg-1", name="busy")
        busy.go_idle()
        busy.go_busy("job-1")
        offline = Agent(cluster_group_id="cg-1", name="offline")
        repo.save_agent(idle)
        repo.save_agent(busy)
        repo.save_agent(offline)
        result = repo.list_idle_agents("cg-1")
        assert len(result) == 1
        assert result[0].name == "idle"

    def test_delete(self, repo):
        agent = Agent(cluster_group_id="cg-1", name="x")
        repo.save_agent(agent)
        assert repo.delete_agent(agent.id) is True
        assert repo.get_agent(agent.id) is None

    def test_update_persists(self, repo):
        agent = Agent(cluster_group_id="cg-1", name="a")
        repo.save_agent(agent)
        agent.go_idle()
        repo.save_agent(agent)
        loaded = repo.get_agent(agent.id)
        assert loaded is not None
        assert loaded.status == AgentStatus.IDLE


class TestChannelMappingContract:
    def test_save_and_get(self, repo):
        m = ChannelMapping(
            org_id="org-1", channel_id="C123", cluster_group_id="cg-1",
        )
        repo.save_channel_mapping(m)
        loaded = repo.get_channel_mapping(m.id)
        assert loaded is not None
        assert loaded.channel_id == "C123"
        assert loaded.mode == ChannelMode.ALERT

    def test_get_by_channel(self, repo):
        m = ChannelMapping(
            org_id="org-1", channel_id="C456", cluster_group_id="cg-1",
        )
        repo.save_channel_mapping(m)
        loaded = repo.get_channel_mapping_by_channel("C456")
        assert loaded is not None
        assert loaded.id == m.id

    def test_get_by_channel_nonexistent(self, repo):
        assert repo.get_channel_mapping_by_channel("C999") is None

    def test_list_by_org(self, repo):
        m1 = ChannelMapping(
            org_id="org-1", channel_id="C1", cluster_group_id="cg-1",
        )
        m2 = ChannelMapping(
            org_id="org-1", channel_id="C2", cluster_group_id="cg-2",
        )
        m3 = ChannelMapping(
            org_id="org-2", channel_id="C3", cluster_group_id="cg-3",
        )
        repo.save_channel_mapping(m1)
        repo.save_channel_mapping(m2)
        repo.save_channel_mapping(m3)
        assert len(repo.list_channel_mappings("org-1")) == 2

    def test_delete(self, repo):
        m = ChannelMapping(
            org_id="org-1", channel_id="C123", cluster_group_id="cg-1",
        )
        repo.save_channel_mapping(m)
        assert repo.delete_channel_mapping(m.id) is True
        assert repo.get_channel_mapping(m.id) is None
        assert repo.delete_channel_mapping(m.id) is False


class TestFilterRuleContract:
    def test_save_and_get(self, repo):
        r = FilterRule(
            channel_mapping_id="cm-1", pattern="CRITICAL",
            action=FilterAction.TRIAGE, priority=5,
        )
        repo.save_filter_rule(r)
        loaded = repo.get_filter_rule(r.id)
        assert loaded is not None
        assert loaded.pattern == "CRITICAL"
        assert loaded.priority == 5

    def test_list_by_channel_mapping(self, repo):
        r1 = FilterRule(channel_mapping_id="cm-1", pattern="ERROR")
        r2 = FilterRule(channel_mapping_id="cm-1", pattern="WARN")
        r3 = FilterRule(channel_mapping_id="cm-2", pattern="CRITICAL")
        repo.save_filter_rule(r1)
        repo.save_filter_rule(r2)
        repo.save_filter_rule(r3)
        assert len(repo.list_filter_rules("cm-1")) == 2

    def test_delete(self, repo):
        r = FilterRule(channel_mapping_id="cm-1", pattern="test")
        repo.save_filter_rule(r)
        assert repo.delete_filter_rule(r.id) is True
        assert repo.get_filter_rule(r.id) is None
        assert repo.delete_filter_rule(r.id) is False


class TestPromptConfigContract:
    def test_save_and_get(self, repo):
        pc = PromptConfig(
            cluster_group_id="cg-1",
            system_prompt="You are a K8s expert",
            stack_manifest="App → Redis → PG",
            persona="DBA",
        )
        repo.save_prompt_config(pc)
        loaded = repo.get_prompt_config(pc.id)
        assert loaded is not None
        assert loaded.system_prompt == "You are a K8s expert"
        assert loaded.persona == "DBA"

    def test_get_by_cluster(self, repo):
        pc = PromptConfig(cluster_group_id="cg-1", system_prompt="test")
        repo.save_prompt_config(pc)
        loaded = repo.get_prompt_config_by_cluster("cg-1")
        assert loaded is not None
        assert loaded.id == pc.id

    def test_get_by_cluster_nonexistent(self, repo):
        assert repo.get_prompt_config_by_cluster("cg-999") is None

    def test_delete(self, repo):
        pc = PromptConfig(cluster_group_id="cg-1")
        repo.save_prompt_config(pc)
        assert repo.delete_prompt_config(pc.id) is True
        assert repo.get_prompt_config(pc.id) is None
        assert repo.delete_prompt_config(pc.id) is False

    def test_update_existing(self, repo):
        pc = PromptConfig(cluster_group_id="cg-1", system_prompt="v1")
        repo.save_prompt_config(pc)
        pc.system_prompt = "v2"
        repo.save_prompt_config(pc)
        loaded = repo.get_prompt_config(pc.id)
        assert loaded is not None
        assert loaded.system_prompt == "v2"
