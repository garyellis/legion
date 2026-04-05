"""Fleet persistence — ABC + SQLite implementation.

Manages Organization, AgentGroup, Agent, ChannelMapping, FilterRule,
and PromptConfig entities.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, Engine, ForeignKey, Integer, String, Text
from sqlalchemy.orm import sessionmaker

from legion.domain.agent import Agent, AgentStatus
from legion.domain.agent_group import AgentGroup, ExecutionMode
from legion.domain.channel_mapping import ChannelMapping, ChannelMode
from legion.domain.filter_rule import FilterAction, FilterRule
from legion.domain.organization import Organization
from legion.domain.project import Project
from legion.domain.prompt_config import PromptConfig
from legion.plumbing.database import Base

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------

class FleetRepository(ABC):
    # Organization
    @abstractmethod
    def save_org(self, org: Organization) -> None: ...

    @abstractmethod
    def get_org(self, org_id: str) -> Optional[Organization]: ...

    @abstractmethod
    def list_orgs(self) -> list[Organization]: ...

    @abstractmethod
    def delete_org(self, org_id: str) -> bool: ...

    # Project
    @abstractmethod
    def save_project(self, project: Project) -> None: ...

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[Project]: ...

    @abstractmethod
    def list_projects(self, org_id: str) -> list[Project]: ...

    @abstractmethod
    def delete_project(self, project_id: str) -> bool: ...

    # AgentGroup
    @abstractmethod
    def save_agent_group(self, ag: AgentGroup) -> None: ...

    @abstractmethod
    def get_agent_group(self, ag_id: str) -> Optional[AgentGroup]: ...

    @abstractmethod
    def get_agent_group_by_registration_token_hash(self, token_hash: str) -> Optional[AgentGroup]: ...

    @abstractmethod
    def list_agent_groups(self, org_id: str) -> list[AgentGroup]: ...

    @abstractmethod
    def list_agent_groups_by_project(self, project_id: str) -> list[AgentGroup]: ...

    @abstractmethod
    def delete_agent_group(self, ag_id: str) -> bool: ...

    # Agent
    @abstractmethod
    def save_agent(self, agent: Agent) -> None: ...

    @abstractmethod
    def get_agent(self, agent_id: str) -> Optional[Agent]: ...

    @abstractmethod
    def list_agents(self, agent_group_id: str) -> list[Agent]: ...

    @abstractmethod
    def list_idle_agents(self, agent_group_id: str) -> list[Agent]: ...

    @abstractmethod
    def delete_agent(self, agent_id: str) -> bool: ...

    # ChannelMapping
    @abstractmethod
    def save_channel_mapping(self, mapping: ChannelMapping) -> None: ...

    @abstractmethod
    def get_channel_mapping(self, mapping_id: str) -> Optional[ChannelMapping]: ...

    @abstractmethod
    def get_channel_mapping_by_channel(self, channel_id: str) -> Optional[ChannelMapping]: ...

    @abstractmethod
    def list_channel_mappings(self, org_id: str) -> list[ChannelMapping]: ...

    @abstractmethod
    def delete_channel_mapping(self, mapping_id: str) -> bool: ...

    # FilterRule
    @abstractmethod
    def save_filter_rule(self, rule: FilterRule) -> None: ...

    @abstractmethod
    def get_filter_rule(self, rule_id: str) -> Optional[FilterRule]: ...

    @abstractmethod
    def list_filter_rules(self, channel_mapping_id: str) -> list[FilterRule]: ...

    @abstractmethod
    def delete_filter_rule(self, rule_id: str) -> bool: ...

    # PromptConfig
    @abstractmethod
    def save_prompt_config(self, config: PromptConfig) -> None: ...

    @abstractmethod
    def get_prompt_config(self, config_id: str) -> Optional[PromptConfig]: ...

    @abstractmethod
    def get_prompt_config_by_agent_group(self, agent_group_id: str) -> Optional[PromptConfig]: ...

    @abstractmethod
    def delete_prompt_config(self, config_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# ORM Row classes
# ---------------------------------------------------------------------------

class OrganizationRow(Base):
    __tablename__ = "organizations"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ProjectRow(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AgentGroupRow(Base):
    __tablename__ = "agent_groups"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    execution_mode = Column(String, nullable=False, default=ExecutionMode.READ_ONLY.value)
    registration_token_hash = Column(String, nullable=True)
    registration_token_rotated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AgentRow(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True)
    agent_group_id = Column(String, ForeignKey("agent_groups.id"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False, default=AgentStatus.OFFLINE.value)
    current_job_id = Column(String, nullable=True)
    capabilities = Column(Text, nullable=False, default="[]")
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class ChannelMappingRow(Base):
    __tablename__ = "channel_mappings"

    id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    channel_id = Column(String, nullable=False, unique=True)
    agent_group_id = Column(String, ForeignKey("agent_groups.id"), nullable=False)
    mode = Column(String, nullable=False, default=ChannelMode.ALERT.value)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class FilterRuleRow(Base):
    __tablename__ = "filter_rules"

    id = Column(String, primary_key=True)
    channel_mapping_id = Column(String, ForeignKey("channel_mappings.id"), nullable=False)
    pattern = Column(String, nullable=False)
    action = Column(String, nullable=False, default=FilterAction.TRIAGE.value)
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class PromptConfigRow(Base):
    __tablename__ = "prompt_configs"

    id = Column(String, primary_key=True)
    agent_group_id = Column(String, ForeignKey("agent_groups.id"), nullable=False, unique=True)
    system_prompt = Column(Text, nullable=False, default="")
    stack_manifest = Column(Text, nullable=False, default="")
    persona = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# SQLite / SQLAlchemy implementation
# ---------------------------------------------------------------------------

class SQLiteFleetRepository(FleetRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    # -- Organization -------------------------------------------------------

    def save_org(self, org: Organization) -> None:
        with self._session_factory() as session:
            row = session.get(OrganizationRow, org.id)
            if row is None:
                row = OrganizationRow(id=org.id)
                session.add(row)
            row.name = org.name
            row.slug = org.slug
            row.created_at = org.created_at
            row.updated_at = org.updated_at
            session.commit()

    def get_org(self, org_id: str) -> Optional[Organization]:
        with self._session_factory() as session:
            row = session.get(OrganizationRow, org_id)
            if row is None:
                return None
            return self._org_to_domain(row)

    def list_orgs(self) -> list[Organization]:
        with self._session_factory() as session:
            rows = session.query(OrganizationRow).all()
            return [self._org_to_domain(r) for r in rows]

    def delete_org(self, org_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(OrganizationRow, org_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- Project ------------------------------------------------------------

    def save_project(self, project: Project) -> None:
        with self._session_factory() as session:
            row = session.get(ProjectRow, project.id)
            if row is None:
                row = ProjectRow(id=project.id)
                session.add(row)
            row.org_id = project.org_id
            row.name = project.name
            row.slug = project.slug
            row.created_at = project.created_at
            row.updated_at = project.updated_at
            session.commit()

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._session_factory() as session:
            row = session.get(ProjectRow, project_id)
            if row is None:
                return None
            return self._project_to_domain(row)

    def list_projects(self, org_id: str) -> list[Project]:
        with self._session_factory() as session:
            rows = (
                session.query(ProjectRow)
                .filter(ProjectRow.org_id == org_id)
                .all()
            )
            return [self._project_to_domain(r) for r in rows]

    def delete_project(self, project_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ProjectRow, project_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- AgentGroup ---------------------------------------------------------

    def save_agent_group(self, ag: AgentGroup) -> None:
        with self._session_factory() as session:
            row = session.get(AgentGroupRow, ag.id)
            if row is None:
                row = AgentGroupRow(id=ag.id)
                session.add(row)
            row.org_id = ag.org_id
            row.project_id = ag.project_id
            row.name = ag.name
            row.slug = ag.slug
            row.environment = ag.environment
            row.provider = ag.provider
            row.execution_mode = ag.execution_mode.value
            row.registration_token_hash = ag.registration_token_hash
            row.registration_token_rotated_at = ag.registration_token_rotated_at
            row.created_at = ag.created_at
            row.updated_at = ag.updated_at
            session.commit()

    def get_agent_group(self, ag_id: str) -> Optional[AgentGroup]:
        with self._session_factory() as session:
            row = session.get(AgentGroupRow, ag_id)
            if row is None:
                return None
            return self._ag_to_domain(row)

    def get_agent_group_by_registration_token_hash(self, token_hash: str) -> Optional[AgentGroup]:
        with self._session_factory() as session:
            row = (
                session.query(AgentGroupRow)
                .filter(AgentGroupRow.registration_token_hash == token_hash)
                .first()
            )
            if row is None:
                return None
            return self._ag_to_domain(row)

    def list_agent_groups(self, org_id: str) -> list[AgentGroup]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentGroupRow)
                .filter(AgentGroupRow.org_id == org_id)
                .all()
            )
            return [self._ag_to_domain(r) for r in rows]

    def list_agent_groups_by_project(self, project_id: str) -> list[AgentGroup]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentGroupRow)
                .filter(AgentGroupRow.project_id == project_id)
                .all()
            )
            return [self._ag_to_domain(r) for r in rows]

    def delete_agent_group(self, ag_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(AgentGroupRow, ag_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- Agent --------------------------------------------------------------

    def save_agent(self, agent: Agent) -> None:
        with self._session_factory() as session:
            row = session.get(AgentRow, agent.id)
            if row is None:
                row = AgentRow(id=agent.id)
                session.add(row)
            row.agent_group_id = agent.agent_group_id
            row.name = agent.name
            row.status = agent.status.value
            row.current_job_id = agent.current_job_id
            row.capabilities = json.dumps(agent.capabilities)
            row.last_heartbeat = agent.last_heartbeat
            row.created_at = agent.created_at
            row.updated_at = agent.updated_at
            session.commit()

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        with self._session_factory() as session:
            row = session.get(AgentRow, agent_id)
            if row is None:
                return None
            return self._agent_to_domain(row)

    def list_agents(self, agent_group_id: str) -> list[Agent]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentRow)
                .filter(AgentRow.agent_group_id == agent_group_id)
                .all()
            )
            return [self._agent_to_domain(r) for r in rows]

    def list_idle_agents(self, agent_group_id: str) -> list[Agent]:
        with self._session_factory() as session:
            rows = (
                session.query(AgentRow)
                .filter(
                    AgentRow.agent_group_id == agent_group_id,
                    AgentRow.status == AgentStatus.IDLE.value,
                )
                .all()
            )
            return [self._agent_to_domain(r) for r in rows]

    def delete_agent(self, agent_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(AgentRow, agent_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _org_to_domain(row: OrganizationRow) -> Organization:
        ensure = SQLiteFleetRepository._ensure_utc
        return Organization(
            id=row.id,
            name=row.name,
            slug=row.slug,
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    @staticmethod
    def _project_to_domain(row: ProjectRow) -> Project:
        ensure = SQLiteFleetRepository._ensure_utc
        return Project(
            id=row.id,
            org_id=row.org_id,
            name=row.name,
            slug=row.slug,
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    @staticmethod
    def _ag_to_domain(row: AgentGroupRow) -> AgentGroup:
        ensure = SQLiteFleetRepository._ensure_utc
        return AgentGroup(
            id=row.id,
            org_id=row.org_id,
            project_id=row.project_id,
            name=row.name,
            slug=row.slug,
            environment=row.environment,
            provider=row.provider,
            execution_mode=ExecutionMode(row.execution_mode),
            registration_token_hash=row.registration_token_hash,
            registration_token_rotated_at=ensure(row.registration_token_rotated_at),
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    @staticmethod
    def _agent_to_domain(row: AgentRow) -> Agent:
        ensure = SQLiteFleetRepository._ensure_utc
        return Agent(
            id=row.id,
            agent_group_id=row.agent_group_id,
            name=row.name,
            status=AgentStatus(row.status),
            current_job_id=row.current_job_id,
            capabilities=json.loads(row.capabilities) if row.capabilities else [],
            last_heartbeat=ensure(row.last_heartbeat),
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    # -- ChannelMapping -----------------------------------------------------

    def save_channel_mapping(self, mapping: ChannelMapping) -> None:
        with self._session_factory() as session:
            row = session.get(ChannelMappingRow, mapping.id)
            if row is None:
                row = ChannelMappingRow(id=mapping.id)
                session.add(row)
            row.org_id = mapping.org_id
            row.channel_id = mapping.channel_id
            row.agent_group_id = mapping.agent_group_id
            row.mode = mapping.mode.value
            row.created_at = mapping.created_at
            row.updated_at = mapping.updated_at
            session.commit()

    def get_channel_mapping(self, mapping_id: str) -> Optional[ChannelMapping]:
        with self._session_factory() as session:
            row = session.get(ChannelMappingRow, mapping_id)
            if row is None:
                return None
            return self._mapping_to_domain(row)

    def get_channel_mapping_by_channel(self, channel_id: str) -> Optional[ChannelMapping]:
        with self._session_factory() as session:
            row = (
                session.query(ChannelMappingRow)
                .filter(ChannelMappingRow.channel_id == channel_id)
                .first()
            )
            if row is None:
                return None
            return self._mapping_to_domain(row)

    def list_channel_mappings(self, org_id: str) -> list[ChannelMapping]:
        with self._session_factory() as session:
            rows = (
                session.query(ChannelMappingRow)
                .filter(ChannelMappingRow.org_id == org_id)
                .all()
            )
            return [self._mapping_to_domain(r) for r in rows]

    def delete_channel_mapping(self, mapping_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ChannelMappingRow, mapping_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- FilterRule ---------------------------------------------------------

    def save_filter_rule(self, rule: FilterRule) -> None:
        with self._session_factory() as session:
            row = session.get(FilterRuleRow, rule.id)
            if row is None:
                row = FilterRuleRow(id=rule.id)
                session.add(row)
            row.channel_mapping_id = rule.channel_mapping_id
            row.pattern = rule.pattern
            row.action = rule.action.value
            row.priority = rule.priority
            row.created_at = rule.created_at
            row.updated_at = rule.updated_at
            session.commit()

    def get_filter_rule(self, rule_id: str) -> Optional[FilterRule]:
        with self._session_factory() as session:
            row = session.get(FilterRuleRow, rule_id)
            if row is None:
                return None
            return self._rule_to_domain(row)

    def list_filter_rules(self, channel_mapping_id: str) -> list[FilterRule]:
        with self._session_factory() as session:
            rows = (
                session.query(FilterRuleRow)
                .filter(FilterRuleRow.channel_mapping_id == channel_mapping_id)
                .all()
            )
            return [self._rule_to_domain(r) for r in rows]

    def delete_filter_rule(self, rule_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(FilterRuleRow, rule_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- PromptConfig -------------------------------------------------------

    def save_prompt_config(self, config: PromptConfig) -> None:
        with self._session_factory() as session:
            row = session.get(PromptConfigRow, config.id)
            if row is None:
                row = PromptConfigRow(id=config.id)
                session.add(row)
            row.agent_group_id = config.agent_group_id
            row.system_prompt = config.system_prompt
            row.stack_manifest = config.stack_manifest
            row.persona = config.persona
            row.created_at = config.created_at
            row.updated_at = config.updated_at
            session.commit()

    def get_prompt_config(self, config_id: str) -> Optional[PromptConfig]:
        with self._session_factory() as session:
            row = session.get(PromptConfigRow, config_id)
            if row is None:
                return None
            return self._prompt_to_domain(row)

    def get_prompt_config_by_agent_group(self, agent_group_id: str) -> Optional[PromptConfig]:
        with self._session_factory() as session:
            row = (
                session.query(PromptConfigRow)
                .filter(PromptConfigRow.agent_group_id == agent_group_id)
                .first()
            )
            if row is None:
                return None
            return self._prompt_to_domain(row)

    def delete_prompt_config(self, config_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(PromptConfigRow, config_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # -- Additional helpers -------------------------------------------------

    @staticmethod
    def _mapping_to_domain(row: ChannelMappingRow) -> ChannelMapping:
        ensure = SQLiteFleetRepository._ensure_utc
        return ChannelMapping(
            id=row.id,
            org_id=row.org_id,
            channel_id=row.channel_id,
            agent_group_id=row.agent_group_id,
            mode=ChannelMode(row.mode),
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    @staticmethod
    def _rule_to_domain(row: FilterRuleRow) -> FilterRule:
        ensure = SQLiteFleetRepository._ensure_utc
        return FilterRule(
            id=row.id,
            channel_mapping_id=row.channel_mapping_id,
            pattern=row.pattern,
            action=FilterAction(row.action),
            priority=row.priority,
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )

    @staticmethod
    def _prompt_to_domain(row: PromptConfigRow) -> PromptConfig:
        ensure = SQLiteFleetRepository._ensure_utc
        return PromptConfig(
            id=row.id,
            agent_group_id=row.agent_group_id,
            system_prompt=row.system_prompt,
            stack_manifest=row.stack_manifest,
            persona=row.persona,
            created_at=ensure(row.created_at),
            updated_at=ensure(row.updated_at),
        )
