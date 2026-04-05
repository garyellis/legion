"""Message persistence — ABC + SQLite implementation."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional, cast

from sqlalchemy import Column, DateTime, Engine, String, Text
from sqlalchemy.orm import sessionmaker

from legion.domain.message import Message, MessageType, AuthorType
from legion.plumbing.database import Base
from legion.services.pagination import Page, decode_cursor, encode_cursor

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE = 200


class MessageRepository(ABC):
    @abstractmethod
    def save(self, message: Message) -> None:
        """Persist a message. Creates or updates if the id already exists (upsert)."""
        ...

    @abstractmethod
    def get_by_id(self, message_id: str) -> Optional[Message]: ...

    @abstractmethod
    def list_by_session(self, session_id: str) -> list[Message]: ...

    @abstractmethod
    def list_by_job(self, job_id: str) -> list[Message]: ...

    @abstractmethod
    def list_by_session_paginated(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[Message]: ...

    @abstractmethod
    def list_by_job_paginated(
        self,
        job_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[Message]: ...

    @abstractmethod
    def purge_before(self, cutoff: datetime) -> int: ...


class MessageRow(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    org_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    author_id = Column(String, nullable=False)
    author_type = Column(String, nullable=False)
    message_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    job_id = Column(String, nullable=True)
    # Column named "metadata" in SQL; aliased to metadata_json to avoid
    # collision with SQLAlchemy DeclarativeBase.metadata.
    metadata_json = Column("metadata", Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False)


class SQLiteMessageRepository(MessageRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._session_factory = sessionmaker(bind=self._engine)

    def save(self, message: Message) -> None:
        with self._session_factory() as session:
            row = session.get(MessageRow, message.id)
            if row is None:
                row = MessageRow(id=message.id)
                session.add(row)
            row_data = cast(Any, row)
            row_data.org_id = message.org_id
            row_data.session_id = message.session_id
            row_data.author_id = message.author_id
            row_data.author_type = message.author_type.value
            row_data.message_type = message.message_type.value
            row_data.content = message.content
            row_data.job_id = message.job_id
            row_data.metadata_json = json.dumps(message.metadata)
            row_data.created_at = message.created_at
            session.commit()

    def get_by_id(self, message_id: str) -> Optional[Message]:
        with self._session_factory() as session:
            row = session.get(MessageRow, message_id)
            if row is None:
                return None
            return self._to_domain(row)

    def list_by_session(self, session_id: str) -> list[Message]:
        with self._session_factory() as session:
            rows = (
                session.query(MessageRow)
                .filter(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at.asc())
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def list_by_job(self, job_id: str) -> list[Message]:
        with self._session_factory() as session:
            rows = (
                session.query(MessageRow)
                .filter(MessageRow.job_id == job_id)
                .order_by(MessageRow.created_at.asc())
                .all()
            )
            return [self._to_domain(row) for row in rows]

    def list_by_session_paginated(
        self,
        session_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[Message]:
        return self._paginated_query(
            filter_column=MessageRow.session_id,
            filter_value=session_id,
            cursor=cursor,
            page_size=page_size,
        )

    def list_by_job_paginated(
        self,
        job_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> Page[Message]:
        return self._paginated_query(
            filter_column=MessageRow.job_id,
            filter_value=job_id,
            cursor=cursor,
            page_size=page_size,
        )

    def purge_before(self, cutoff: datetime) -> int:
        with self._session_factory() as session:
            count = (
                session.query(MessageRow)
                .filter(MessageRow.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            session.commit()
            return count

    def _paginated_query(
        self,
        *,
        filter_column: Any,
        filter_value: str,
        cursor: str | None,
        page_size: int,
    ) -> Page[Message]:
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        with self._session_factory() as session:
            query = (
                session.query(MessageRow)
                .filter(filter_column == filter_value)
            )
            if cursor is not None:
                cursor_ts, cursor_id = decode_cursor(cursor)
                query = query.filter(
                    (MessageRow.created_at > cursor_ts)
                    | (
                        (MessageRow.created_at == cursor_ts)
                        & (MessageRow.id > cursor_id)
                    )
                )
            query = query.order_by(
                MessageRow.created_at.asc(), MessageRow.id.asc()
            )
            rows = query.limit(page_size + 1).all()
            has_more = len(rows) > page_size
            items = [self._to_domain(row) for row in rows[:page_size]]
            next_cursor: str | None = None
            if has_more and items:
                last = items[-1]
                next_cursor = encode_cursor(last.created_at, last.id)
            return Page(items=items, next_cursor=next_cursor, has_more=has_more)

    @staticmethod
    def _ensure_utc(dt: datetime | None) -> datetime | None:
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _to_domain(row: MessageRow) -> Message:
        ensure = SQLiteMessageRepository._ensure_utc
        row_data = cast(Any, row)
        return Message(
            id=row_data.id,
            org_id=row_data.org_id,
            session_id=row_data.session_id,
            author_id=row_data.author_id,
            author_type=AuthorType(row_data.author_type),
            message_type=MessageType(row_data.message_type),
            content=row_data.content,
            job_id=row_data.job_id,
            metadata=json.loads(row_data.metadata_json or "{}"),
            created_at=cast(datetime, ensure(row_data.created_at)),
        )
