"""Persisted short-lived agent session token storage."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional, cast

from sqlalchemy import Column, DateTime, Engine, String
from sqlalchemy.orm import sessionmaker

from legion.domain.agent_auth import AgentSessionToken
from legion.plumbing.database import Base


class AgentSessionRepository(ABC):
    @abstractmethod
    def save(self, token: AgentSessionToken) -> None: ...

    @abstractmethod
    def delete(self, token_id: str) -> bool: ...

    @abstractmethod
    def delete_for_agent(self, agent_id: str) -> int: ...

    @abstractmethod
    def get_by_id(self, token_id: str) -> Optional[AgentSessionToken]: ...

    @abstractmethod
    def get_active_by_token_hash(self, token_hash: str) -> Optional[AgentSessionToken]: ...


class AgentSessionTokenRow(Base):
    __tablename__ = "agent_session_tokens"

    id = Column(String, primary_key=True)
    agent_id = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class SQLiteAgentSessionRepository(AgentSessionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, token: AgentSessionToken) -> None:
        with self._session_factory() as db:
            row = db.get(AgentSessionTokenRow, token.id)
            if row is None:
                row = AgentSessionTokenRow(id=token.id)
                db.add(row)
            db_row = cast(Any, row)
            db_row.agent_id = token.agent_id
            db_row.token_hash = token.token_hash
            db_row.expires_at = token.expires_at
            db_row.created_at = token.created_at
            db.commit()

    def delete(self, token_id: str) -> bool:
        with self._session_factory() as db:
            row = db.get(AgentSessionTokenRow, token_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def delete_for_agent(self, agent_id: str) -> int:
        with self._session_factory() as db:
            rows = db.query(AgentSessionTokenRow).filter(
                AgentSessionTokenRow.agent_id == agent_id,
            ).all()
            count = len(rows)
            for row in rows:
                db.delete(row)
            db.commit()
            return count

    def get_by_id(self, token_id: str) -> Optional[AgentSessionToken]:
        with self._session_factory() as db:
            row = db.get(AgentSessionTokenRow, token_id)
            if row is None:
                return None
            return self._to_domain(row)

    def get_active_by_token_hash(self, token_hash: str) -> Optional[AgentSessionToken]:
        with self._session_factory() as db:
            now = datetime.now(timezone.utc)
            row = (
                db.query(AgentSessionTokenRow)
                .filter(
                    AgentSessionTokenRow.token_hash == token_hash,
                    AgentSessionTokenRow.expires_at > now,
                )
                .first()
            )
            if row is None:
                return None
            return self._to_domain(row)

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _to_domain(row: AgentSessionTokenRow) -> AgentSessionToken:
        ensure = SQLiteAgentSessionRepository._ensure_utc
        db_row = cast(Any, row)
        expires_at = ensure(db_row.expires_at)
        created_at = ensure(db_row.created_at)
        assert expires_at is not None
        assert created_at is not None
        return AgentSessionToken(
            id=db_row.id,
            agent_id=db_row.agent_id,
            token_hash=db_row.token_hash,
            expires_at=expires_at,
            created_at=created_at,
        )
