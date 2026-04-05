"""Tests for agent auth token helpers and value objects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from legion.domain.agent import Agent
from legion.domain.agent_auth import (
    AgentGroupTokenRotationResult,
    AgentRegistrationResult,
    AgentSessionToken,
)
from legion.domain.agent_group import AgentGroup
from legion.plumbing.tokens import generate_token, hash_token, tokens_match


def test_token_helpers_generate_and_match():
    token = generate_token()
    assert token
    assert tokens_match(token, hash_token(token))


def test_agent_session_token_expiry():
    token = AgentSessionToken(
        agent_id="agent-1",
        token_hash="hash",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    assert token.is_expired()


def test_registration_result_models_round_trip():
    agent = Agent(agent_group_id="ag-1", name="agent-1")
    registration = AgentRegistrationResult(
        agent=agent,
        session_token="session-token",
        session_token_expires_at=datetime.now(timezone.utc),
    )
    rotation = AgentGroupTokenRotationResult(
        agent_group=AgentGroup(
            org_id="org-1",
            project_id="proj-1",
            name="group",
            slug="group",
            environment="dev",
            provider="aks",
        ),
        registration_token="reg-token",
    )

    assert registration.session_token == "session-token"
    assert rotation.registration_token == "reg-token"
