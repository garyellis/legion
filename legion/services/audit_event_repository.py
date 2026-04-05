"""Audit event persistence — ABC + SQLite implementation."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import Column, DateTime, Engine, Integer, String, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from legion.domain.audit_event import AuditAction, AuditEvent
from legion.plumbing.database import Base
from legion.services.pagination import Page, decode_cursor, encode_cursor

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 500


class AuditEventRepository(ABC):
    @abstractmethod
    def save(self, event: AuditEvent) -> None:
        """Insert an audit event. Silently ignores duplicates (insert-only, not upsert)."""
        ...

    @abstractmethod
    def save_batch(self, events: list[AuditEvent]) -> None: ...

    @abstractmethod
    def get_by_id(self, event_id: str) -> AuditEvent | None: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[AuditEvent]: ...

    @abstractmethod
    def list_by_session(self, session_id: str) -> list[AuditEvent]: ...

    @abstractmethod
    def list_by_org(self, org_id: str, *, limit: int = 100) -> list[AuditEvent]: ...

    @abstractmethod
    def list_by_job_paginated(
        self,
        job_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> Page[AuditEvent]: ...

    @abstractmethod
    def list_by_session_paginated(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> Page[AuditEvent]: ...

    @abstractmethod
    def purge_before(self, cutoff: datetime) -> int: ...


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True)
    job_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    org_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    tool_name = Column(String, nullable=True)
    input_json = Column(Text, nullable=True)
    output_json = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class SQLiteAuditEventRepository(AuditEventRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, event: AuditEvent) -> None:
        with self._session_factory() as session:
            row = AuditEventRow(
                id=event.id,
                job_id=event.job_id,
                agent_id=event.agent_id,
                session_id=event.session_id,
                org_id=event.org_id,
                action=event.action.value,
                tool_name=event.tool_name,
                input_json=json.dumps(event.input) if event.input is not None else None,
                output_json=json.dumps(event.output) if event.output is not None else None,
                duration_ms=event.duration_ms,
                created_at=event.created_at,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                logger.warning("Duplicate audit event ignored: %s", event.id)

    def save_batch(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        with self._session_factory() as session:
            for event in events:
                row = AuditEventRow(
                    id=event.id,
                    job_id=event.job_id,
                    agent_id=event.agent_id,
                    session_id=event.session_id,
                    org_id=event.org_id,
                    action=event.action.value,
                    tool_name=event.tool_name,
                    input_json=json.dumps(event.input) if event.input is not None else None,
                    output_json=json.dumps(event.output) if event.output is not None else None,
                    duration_ms=event.duration_ms,
                    created_at=event.created_at,
                )
                session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                # Fall back to individual saves to handle partial duplicates
                for event in events:
                    self.save(event)
            except Exception:
                session.rollback()
                logger.error("Failed to save batch of %d audit events", len(events), exc_info=True)
                raise

    def get_by_id(self, event_id: str) -> AuditEvent | None:
        with self._session_factory() as session:
            row = session.get(AuditEventRow, event_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list_by_job(self, job_id: str) -> list[AuditEvent]:
        with self._session_factory() as session:
            rows = (
                session.query(AuditEventRow)
                .filter(AuditEventRow.job_id == job_id)
                .order_by(AuditEventRow.created_at.asc())
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def list_by_session(self, session_id: str) -> list[AuditEvent]:
        with self._session_factory() as session:
            rows = (
                session.query(AuditEventRow)
                .filter(AuditEventRow.session_id == session_id)
                .order_by(AuditEventRow.created_at.asc())
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def list_by_org(self, org_id: str, *, limit: int = 100) -> list[AuditEvent]:
        effective_limit = max(1, min(limit, 1000))
        with self._session_factory() as session:
            rows = (
                session.query(AuditEventRow)
                .filter(AuditEventRow.org_id == org_id)
                .order_by(AuditEventRow.created_at.desc())  # newest first for org views
                .limit(effective_limit)
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def list_by_job_paginated(
        self,
        job_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> Page[AuditEvent]:
        effective_size = max(1, min(page_size, MAX_PAGE_SIZE))
        with self._session_factory() as session:
            query = session.query(AuditEventRow).filter(
                AuditEventRow.job_id == job_id
            )
            if cursor is not None:
                cursor_ts, cursor_id = decode_cursor(cursor)
                query = query.filter(
                    (AuditEventRow.created_at > cursor_ts)
                    | (
                        (AuditEventRow.created_at == cursor_ts)
                        & (AuditEventRow.id > cursor_id)
                    )
                )
            rows = (
                query.order_by(
                    AuditEventRow.created_at.asc(), AuditEventRow.id.asc()
                )
                .limit(effective_size + 1)  # fetch one extra to detect has_more
                .all()
            )
            has_more = len(rows) > effective_size
            items_rows = rows[:effective_size]
            items = [self._to_domain(r) for r in items_rows]
            next_cursor = (
                encode_cursor(items[-1].created_at, items[-1].id)
                if has_more and items
                else None
            )
            return Page(items=items, next_cursor=next_cursor, has_more=has_more)

    def list_by_session_paginated(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 100,
    ) -> Page[AuditEvent]:
        effective_size = max(1, min(page_size, MAX_PAGE_SIZE))
        with self._session_factory() as session:
            query = session.query(AuditEventRow).filter(
                AuditEventRow.session_id == session_id
            )
            if cursor is not None:
                cursor_ts, cursor_id = decode_cursor(cursor)
                query = query.filter(
                    (AuditEventRow.created_at > cursor_ts)
                    | (
                        (AuditEventRow.created_at == cursor_ts)
                        & (AuditEventRow.id > cursor_id)
                    )
                )
            rows = (
                query.order_by(
                    AuditEventRow.created_at.asc(), AuditEventRow.id.asc()
                )
                .limit(effective_size + 1)
                .all()
            )
            has_more = len(rows) > effective_size
            items_rows = rows[:effective_size]
            items = [self._to_domain(r) for r in items_rows]
            next_cursor = (
                encode_cursor(items[-1].created_at, items[-1].id)
                if has_more and items
                else None
            )
            return Page(items=items, next_cursor=next_cursor, has_more=has_more)

    def purge_before(self, cutoff: datetime) -> int:
        with self._session_factory() as session:
            count = (
                session.query(AuditEventRow)
                .filter(AuditEventRow.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    # NOTE: Pydantic re-validates fields on construction. If AuditEvent
    # validators are tightened in the future, historical records may fail
    # to load. Use model_construct() if this becomes an issue.
    @staticmethod
    def _to_domain(row: AuditEventRow) -> AuditEvent:
        ensure = SQLiteAuditEventRepository._ensure_utc
        row_data = cast(Any, row)
        return AuditEvent(
            id=row_data.id,
            job_id=row_data.job_id,
            agent_id=row_data.agent_id,
            session_id=row_data.session_id,
            org_id=row_data.org_id,
            action=AuditAction(row_data.action),
            tool_name=row_data.tool_name,
            input=json.loads(row_data.input_json) if row_data.input_json is not None else None,
            output=json.loads(row_data.output_json) if row_data.output_json is not None else None,
            duration_ms=row_data.duration_ms,
            created_at=cast(datetime, ensure(row_data.created_at)),
        )
