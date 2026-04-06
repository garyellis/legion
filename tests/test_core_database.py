"""Tests for legion.core.database tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from legion.core.database import db_connection_check
from legion.core.database import db_query
from legion.core.database import db_table_schema
from legion.core.database import db_tables
from legion.core.database import tools as dbtools
from legion.plumbing.database import create_engine


def _sqlite_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def _build_sample_database(db_path: Path) -> str:
    engine = create_engine(_sqlite_url(db_path))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE widgets (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'general'
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE widget_tags (
                id INTEGER PRIMARY KEY,
                widget_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                FOREIGN KEY(widget_id) REFERENCES widgets(id)
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO widgets (id, name, category) VALUES (1, 'alpha', 'ops')"
        )
        connection.exec_driver_sql(
            "INSERT INTO widgets (id, name, category) VALUES (2, 'beta', 'platform')"
        )
    engine.dispose()
    return _sqlite_url(db_path)


def _build_large_payload_database(db_path: Path, *, row_count: int, payload_size: int) -> str:
    engine = create_engine(_sqlite_url(db_path))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE payloads (
                id INTEGER PRIMARY KEY,
                body TEXT NOT NULL
            )
            """
        )
        payload = "x" * payload_size
        for row_id in range(1, row_count + 1):
            connection.exec_driver_sql(
                "INSERT INTO payloads (id, body) VALUES (?, ?)",
                (row_id, payload),
            )
    engine.dispose()
    return _sqlite_url(db_path)


def test_database_package_reexports_tool_functions_and_metadata() -> None:
    assert db_query is dbtools.db_query
    assert db_tables is dbtools.db_tables
    assert db_table_schema is dbtools.db_table_schema
    assert db_connection_check is dbtools.db_connection_check

    meta = db_query.__tool_meta__  # type: ignore[attr-defined]
    assert meta.name == "db_query"
    assert meta.category == "database"
    assert meta.read_only is True

    schema_meta = db_table_schema.__tool_meta__  # type: ignore[attr-defined]
    assert schema_meta.name == "db_table_schema"
    assert schema_meta.category == "database"
    assert schema_meta.read_only is True


def test_db_query_returns_rows_and_truncates(tmp_path: Path) -> None:
    url = _build_sample_database(tmp_path / "query.db")

    result = db_query(url, "SELECT id, name FROM widgets ORDER BY id", limit=1)

    assert result == "\n".join(
        [
            "Query returned at least 2 row(s).",
            "Columns: id, name",
            "- Row 1: id=1, name=alpha",
            "Results truncated at 1 row(s).",
        ]
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("UPDATE widgets SET name = 'gamma'", "Only read-only queries are allowed."),
        ("WITH cte AS (SELECT 1) SELECT * FROM cte", "Only read-only queries are allowed."),
        ("EXPLAIN SELECT * FROM widgets", "Only read-only queries are allowed."),
    ],
)
def test_db_query_rejects_non_select_sql(
    tmp_path: Path,
    query: str,
    expected: str,
) -> None:
    url = _build_sample_database(tmp_path / "reject.db")

    result = db_query(url, query)

    assert result == expected


def test_db_query_truncates_cell_values(tmp_path: Path) -> None:
    url = _build_large_payload_database(
        tmp_path / "cell-truncation.db",
        row_count=1,
        payload_size=600,
    )

    result = db_query(url, "SELECT id, body FROM payloads", limit=1)

    assert "x" * 600 not in result
    assert "...[truncated]" in result
    assert not result.endswith("\n...[truncated]")


def test_db_query_truncates_total_output(tmp_path: Path) -> None:
    url = _build_large_payload_database(
        tmp_path / "output-truncation.db",
        row_count=40,
        payload_size=600,
    )

    result = db_query(url, "SELECT id, body FROM payloads ORDER BY id", limit=100)

    assert len(result) == dbtools.MAX_TOTAL_OUTPUT_CHARS
    assert result.endswith("\n...[truncated]")
    assert result.count("...[truncated]") >= 2


def test_db_query_formats_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenEngine:
        def connect(self) -> None:
            raise OperationalError(
                "SELECT 1",
                {},
                RuntimeError("password=supersecret connection refused"),
            )

        def dispose(self) -> None:
            return None

    monkeypatch.setattr(dbtools, "create_engine", lambda _url: BrokenEngine())

    result = db_query("sqlite:///unused.db", "SELECT 1")

    assert result == "Database query failed: connection_failed"
    assert "supersecret" not in result


def test_db_query_applies_connection_and_statement_budgets() -> None:
    url = dbtools._connection_url_with_connect_timeout(
        "postgresql://user:secret@localhost/example?application_name=legion"
    )

    assert "connect_timeout=10" in url
    assert "application_name=legion" in url
    assert "secret" in url

    class FakeDialect:
        name = "postgresql"

    class FakeConnection:
        dialect = FakeDialect()

        def __init__(self) -> None:
            self.statements: list[str] = []

        def exec_driver_sql(self, statement: str) -> None:
            self.statements.append(statement)

    connection = FakeConnection()

    dbtools._apply_statement_timeout(connection)

    assert connection.statements == [
        f"SET statement_timeout = {dbtools.MAX_STATEMENT_TIMEOUT_MILLISECONDS}"
    ]


def test_db_query_fails_closed_when_statement_timeout_cannot_be_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDialect:
        name = "postgresql"

    class FakeConnection:
        dialect = FakeDialect()

        def __init__(self) -> None:
            self.executed = False

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            return None

        def exec_driver_sql(self, statement: str) -> None:
            raise OperationalError(
                statement,
                {},
                RuntimeError("statement_timeout refused"),
            )

        def execute(self, statement: object) -> None:
            self.executed = True
            raise AssertionError("query execution should not be reached")

        def mappings(self) -> object:
            raise AssertionError("query mappings should not be reached")

    class FakeEngine:
        def __init__(self, connection: FakeConnection) -> None:
            self.connection = connection
            self.disposed = False

        def connect(self) -> FakeConnection:
            return self.connection

        def dispose(self) -> None:
            self.disposed = True

    fake_connection = FakeConnection()
    fake_engine = FakeEngine(fake_connection)
    monkeypatch.setattr(dbtools, "create_engine", lambda _url: fake_engine)

    result = db_query("postgresql://user:secret@localhost/example", "SELECT 1")

    assert result == "Database query failed: timeout"
    assert fake_connection.executed is False
    assert fake_engine.disposed is True


def test_db_tables_and_schema_format_output(tmp_path: Path) -> None:
    url = _build_sample_database(tmp_path / "schema.db")

    tables = db_tables(url)
    assert tables == "Tables in schema public:\n- widget_tags\n- widgets"

    schema = db_table_schema(url, "widget_tags")
    assert schema == "\n".join(
        [
            "Table schema for widget_tags in schema public:",
            "Columns:",
            "- id: INTEGER; PRIMARY KEY",
            "- widget_id: INTEGER; NOT NULL",
            "- tag: TEXT; NOT NULL",
            "Primary key: id",
            "Unique constraints: <none>",
            "Foreign keys:",
            "- widget_id -> widgets.id",
        ]
    )


def test_db_connection_check_reports_success(tmp_path: Path) -> None:
    url = _build_sample_database(tmp_path / "check.db")

    result = db_connection_check(url)

    assert result.startswith("Connection successful.\nDialect: sqlite\nVersion: SQLite ")
