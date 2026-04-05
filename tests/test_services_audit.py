"""Tests for AuditService, BufferedAuditWriter, and SQLiteAuditEventRepository."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from legion.domain.audit_event import AuditAction, AuditEvent
from legion.plumbing.database import create_all, create_engine
from legion.services.audit_event_repository import SQLiteAuditEventRepository
from legion.services.audit_service import AuditService
from legion.services.buffered_audit_writer import BufferedAuditWriter


def _make_event(**overrides) -> AuditEvent:
    defaults = {
        "job_id": "job-1",
        "agent_id": "agent-1",
        "session_id": "session-1",
        "org_id": "org-1",
        "action": AuditAction.TOOL_CALL,
    }
    defaults.update(overrides)
    return AuditEvent(**defaults)


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLiteAuditEventRepository(engine)


class TestSQLiteAuditEventRepository:
    def test_save_and_retrieve_by_job_id(self, repo):
        event = _make_event(job_id="job-42", tool_name="kubectl")
        repo.save(event)
        results = repo.list_by_job("job-42")
        assert len(results) == 1
        assert results[0].id == event.id
        assert results[0].job_id == "job-42"
        assert results[0].tool_name == "kubectl"

    def test_save_and_retrieve_by_session_id(self, repo):
        event = _make_event(session_id="sess-99")
        repo.save(event)
        results = repo.list_by_session("sess-99")
        assert len(results) == 1
        assert results[0].id == event.id
        assert results[0].session_id == "sess-99"

    def test_list_by_job_returns_empty_for_unknown(self, repo):
        assert repo.list_by_job("unknown-job") == []

    def test_list_by_session_returns_empty_for_unknown(self, repo):
        assert repo.list_by_session("unknown-session") == []

    def test_ordering_by_created_at(self, repo):
        now = datetime.now(timezone.utc)
        early = _make_event(
            job_id="job-1",
            action=AuditAction.TOOL_CALL,
            created_at=now - timedelta(seconds=10),
        )
        late = _make_event(
            job_id="job-1",
            action=AuditAction.TOOL_RESULT,
            created_at=now,
        )
        # Save in reverse order to confirm ordering is by created_at, not insert order
        repo.save(late)
        repo.save(early)
        results = repo.list_by_job("job-1")
        assert len(results) == 2
        assert results[0].id == early.id
        assert results[1].id == late.id

    def test_input_output_round_trip(self, repo):
        event = _make_event(
            input={"namespace": "prod", "count": 3},
            output={"pods": ["a", "b"], "details": {"status": "ok"}},
        )
        repo.save(event)
        loaded = repo.list_by_job("job-1")[0]
        assert loaded.input == {"namespace": "prod", "count": 3}
        assert loaded.output == {"pods": ["a", "b"], "details": {"status": "ok"}}

    def test_none_input_output_round_trip(self, repo):
        event = _make_event()
        repo.save(event)
        loaded = repo.list_by_job("job-1")[0]
        assert loaded.input is None
        assert loaded.output is None

    def test_save_duplicate_id_logs_warning(self, repo, caplog):
        event = _make_event(id="dup-id-1")
        repo.save(event)
        with caplog.at_level(logging.WARNING):
            repo.save(event)
        assert "Duplicate audit event ignored: dup-id-1" in caplog.text
        # Only one row persisted
        assert len(repo.list_by_job("job-1")) == 1

    def test_save_batch_multiple_events(self, repo):
        events = [
            _make_event(id=f"batch-{i}", job_id="job-batch")
            for i in range(5)
        ]
        repo.save_batch(events)
        results = repo.list_by_job("job-batch")
        assert len(results) == 5

    def test_save_batch_empty_list(self, repo):
        # Should not raise
        repo.save_batch([])

    def test_save_batch_with_partial_duplicates(self, repo):
        event = _make_event(id="pre-existing", job_id="job-batch2")
        repo.save(event)
        events = [
            _make_event(id="pre-existing", job_id="job-batch2"),
            _make_event(id="new-event", job_id="job-batch2"),
        ]
        repo.save_batch(events)
        results = repo.list_by_job("job-batch2")
        assert len(results) == 2

    def test_get_by_id_found(self, repo):
        event = _make_event(id="lookup-1", tool_name="helm")
        repo.save(event)
        loaded = repo.get_by_id("lookup-1")
        assert loaded is not None
        assert loaded.id == "lookup-1"
        assert loaded.tool_name == "helm"

    def test_get_by_id_not_found(self, repo):
        assert repo.get_by_id("nonexistent") is None

    def test_list_by_org_basic(self, repo):
        for i in range(3):
            repo.save(_make_event(id=f"org-evt-{i}", org_id="org-A"))
        repo.save(_make_event(id="other-org", org_id="org-B"))

        results = repo.list_by_org("org-A")
        assert len(results) == 3
        assert all(r.org_id == "org-A" for r in results)

    def test_list_by_org_limit(self, repo):
        for i in range(5):
            repo.save(
                _make_event(
                    id=f"org-lim-{i}",
                    org_id="org-C",
                    created_at=datetime.now(timezone.utc) + timedelta(seconds=i),
                )
            )
        results = repo.list_by_org("org-C", limit=3)
        assert len(results) == 3

    def test_list_by_org_newest_first(self, repo):
        now = datetime.now(timezone.utc)
        repo.save(_make_event(id="old", org_id="org-D", created_at=now - timedelta(hours=1)))
        repo.save(_make_event(id="new", org_id="org-D", created_at=now))
        results = repo.list_by_org("org-D")
        assert results[0].id == "new"
        assert results[1].id == "old"

    def test_list_by_job_paginated_cursor_navigation(self, repo):
        now = datetime.now(timezone.utc)
        # Create 5 events with distinct timestamps
        for i in range(5):
            repo.save(
                _make_event(
                    id=f"pg-{i}",
                    job_id="job-paged",
                    created_at=now + timedelta(seconds=i),
                )
            )

        # Page 1: first 2
        page1 = repo.list_by_job_paginated("job-paged", page_size=2)
        assert len(page1.items) == 2
        assert page1.has_more is True
        assert page1.next_cursor is not None
        assert page1.items[0].id == "pg-0"
        assert page1.items[1].id == "pg-1"

        # Page 2: next 2
        page2 = repo.list_by_job_paginated(
            "job-paged", cursor=page1.next_cursor, page_size=2
        )
        assert len(page2.items) == 2
        assert page2.has_more is True
        assert page2.next_cursor is not None
        assert page2.items[0].id == "pg-2"
        assert page2.items[1].id == "pg-3"

        # Page 3: last 1
        page3 = repo.list_by_job_paginated(
            "job-paged", cursor=page2.next_cursor, page_size=2
        )
        assert len(page3.items) == 1
        assert page3.has_more is False
        assert page3.next_cursor is None
        assert page3.items[0].id == "pg-4"

    def test_list_by_job_paginated_empty(self, repo):
        page = repo.list_by_job_paginated("nonexistent-job")
        assert page.items == []
        assert page.has_more is False
        assert page.next_cursor is None

    def test_list_by_session_paginated_basic(self, repo):
        now = datetime.now(timezone.utc)
        for i in range(3):
            repo.save(
                _make_event(
                    id=f"sp-{i}",
                    session_id="sess-paged",
                    created_at=now + timedelta(seconds=i),
                )
            )

        page = repo.list_by_session_paginated("sess-paged", page_size=10)
        assert len(page.items) == 3
        assert page.has_more is False
        assert page.next_cursor is None

    def test_list_by_session_paginated_with_cursor(self, repo):
        now = datetime.now(timezone.utc)
        for i in range(4):
            repo.save(
                _make_event(
                    id=f"spc-{i}",
                    session_id="sess-paged2",
                    created_at=now + timedelta(seconds=i),
                )
            )

        page1 = repo.list_by_session_paginated("sess-paged2", page_size=2)
        assert len(page1.items) == 2
        assert page1.has_more is True

        page2 = repo.list_by_session_paginated(
            "sess-paged2", cursor=page1.next_cursor, page_size=2
        )
        assert len(page2.items) == 2
        assert page2.has_more is False

    def test_purge_before_deletes_old_keeps_recent(self, repo):
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)

        old = _make_event(id="old-purge", job_id="job-purge", created_at=now - timedelta(hours=2))
        recent = _make_event(id="recent-purge", job_id="job-purge", created_at=now)
        repo.save(old)
        repo.save(recent)

        deleted = repo.purge_before(cutoff)
        assert deleted == 1

        remaining = repo.list_by_job("job-purge")
        assert len(remaining) == 1
        assert remaining[0].id == "recent-purge"

    def test_list_by_job_paginated_malformed_cursor(self, repo):
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            repo.list_by_job_paginated("job-1", cursor="not-a-valid-cursor")

    def test_purge_before_returns_zero_when_nothing_to_delete(self, repo):
        now = datetime.now(timezone.utc)
        repo.save(_make_event(id="keep-me", created_at=now))
        deleted = repo.purge_before(now - timedelta(hours=1))
        assert deleted == 0


class TestAuditService:
    def test_emit_persists_event(self, repo):
        service = AuditService(repo, buffered=False)
        event = _make_event(tool_name="kubectl")
        service.emit(event)
        results = repo.list_by_job("job-1")
        assert len(results) == 1
        assert results[0].tool_name == "kubectl"

    def test_emit_suppresses_exceptions(self):
        mock_repo = MagicMock()
        mock_repo.save.side_effect = RuntimeError("db exploded")
        service = AuditService(mock_repo, buffered=False)
        event = _make_event()
        # Must not raise
        service.emit(event)
        mock_repo.save.assert_called_once_with(event)


class TestBufferedAuditWriter:
    def test_flush_on_count_threshold(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=3, flush_interval_seconds=60.0)
        events = [_make_event(id=f"thresh-{i}", job_id="job-thresh") for i in range(3)]
        for e in events:
            writer.append(e)
        # Threshold reached — events should be persisted without explicit flush
        results = repo.list_by_job("job-thresh")
        assert len(results) == 3

    def test_flush_on_explicit_call(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=60.0)
        events = [_make_event(id=f"expl-{i}", job_id="job-expl") for i in range(2)]
        for e in events:
            writer.append(e)
        # Below threshold — not yet persisted
        assert repo.list_by_job("job-expl") == []
        writer.flush()
        results = repo.list_by_job("job-expl")
        assert len(results) == 2

    def test_timer_flush(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=0.05)
        writer.append(_make_event(id="timer-1", job_id="job-timer"))
        # 10x margin over flush interval to avoid CI flakiness
        time.sleep(0.5)
        results = repo.list_by_job("job-timer")
        assert len(results) == 1

    def test_close_flushes_remaining(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=60.0)
        events = [_make_event(id=f"close-{i}", job_id="job-close") for i in range(4)]
        for e in events:
            writer.append(e)
        writer.close()
        results = repo.list_by_job("job-close")
        assert len(results) == 4

    def test_closed_writer_drops_events(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=60.0)
        writer.append(_make_event(id="before-close", job_id="job-drop"))
        writer.close()
        assert len(repo.list_by_job("job-drop")) == 1
        # After close, new events are dropped
        writer.append(_make_event(id="after-close", job_id="job-drop"))
        assert len(repo.list_by_job("job-drop")) == 1

    def test_pending_count(self, repo):
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=60.0)
        assert writer.pending_count == 0
        writer.append(_make_event(id="pc-1"))
        writer.append(_make_event(id="pc-2"))
        assert writer.pending_count == 2
        writer.flush()
        assert writer.pending_count == 0

    def test_concurrent_appends_no_data_loss(self, repo):
        """Multiple threads appending simultaneously should not lose events."""
        import threading
        writer = BufferedAuditWriter(repo, max_batch_size=100, flush_interval_seconds=60.0)
        num_threads = 4
        events_per_thread = 25
        barrier = threading.Barrier(num_threads)

        def worker(thread_id: int) -> None:
            barrier.wait()  # Synchronize start
            for i in range(events_per_thread):
                event = _make_event(
                    id=f"concurrent-{thread_id}-{i}",
                    job_id="job-concurrent",
                )
                writer.append(event)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        writer.close()
        events = repo.list_by_job("job-concurrent")
        assert len(events) == num_threads * events_per_thread


class TestAuditServiceBuffered:
    def test_emit_buffers_by_default(self, repo):
        service = AuditService(repo, flush_interval_seconds=60.0)
        event = _make_event(tool_name="helm", job_id="job-buf")
        service.emit(event)
        # Not yet in repo — buffered
        assert repo.list_by_job("job-buf") == []
        service.flush()
        results = repo.list_by_job("job-buf")
        assert len(results) == 1
        assert results[0].tool_name == "helm"

    def test_buffered_emit_then_paginate(self, repo):
        """End-to-end: emit through buffered service, flush, paginate results."""
        service = AuditService(repo, buffered=True, max_batch_size=50, flush_interval_seconds=60.0)

        # Emit 5 events
        for i in range(5):
            event = _make_event(
                id=f"e2e-{i}",
                job_id="job-e2e",
                created_at=datetime(2026, 4, 5, 12, 0, i, tzinfo=timezone.utc),
            )
            service.emit(event)

        service.flush()

        # Paginate with page_size=2
        page1 = repo.list_by_job_paginated("job-e2e", page_size=2)
        assert len(page1.items) == 2
        assert page1.has_more is True

        page2 = repo.list_by_job_paginated("job-e2e", cursor=page1.next_cursor, page_size=2)
        assert len(page2.items) == 2
        assert page2.has_more is True

        page3 = repo.list_by_job_paginated("job-e2e", cursor=page2.next_cursor, page_size=2)
        assert len(page3.items) == 1
        assert page3.has_more is False

        all_ids = [e.id for e in page1.items + page2.items + page3.items]
        assert all_ids == [f"e2e-{i}" for i in range(5)]

    def test_emit_unbuffered(self, repo):
        service = AuditService(repo, buffered=False)
        event = _make_event(tool_name="kubectl", job_id="job-unbuf")
        service.emit(event)
        # Immediately in repo
        results = repo.list_by_job("job-unbuf")
        assert len(results) == 1
        assert results[0].tool_name == "kubectl"
