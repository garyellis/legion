"""Tests for the agent session token repository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from legion.domain.agent_auth import AgentSessionToken
from legion.plumbing.database import create_all, create_engine
from legion.plumbing.tokens import hash_token
from legion.services.agent_session_repository import SQLiteAgentSessionRepository


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteAgentSessionRepository(engine)


def test_save_and_get(repo):
    token = AgentSessionToken(
        agent_id="agent-1",
        token_hash=hash_token("token-1"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    repo.save(token)

    loaded = repo.get_by_id(token.id)
    assert loaded is not None
    assert loaded.agent_id == "agent-1"


def test_get_active_by_token_hash(repo):
    raw = "token-2"
    token = AgentSessionToken(
        agent_id="agent-1",
        token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    repo.save(token)

    loaded = repo.get_active_by_token_hash(hash_token(raw))
    assert loaded is not None
    assert loaded.id == token.id


def test_delete_for_agent(repo):
    token = AgentSessionToken(
        agent_id="agent-1",
        token_hash=hash_token("token-3"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    repo.save(token)

    assert repo.delete_for_agent("agent-1") == 1
    assert repo.get_by_id(token.id) is None
