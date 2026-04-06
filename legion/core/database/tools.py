"""Database inspection tools."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from legion.plumbing.database import create_engine
from legion.plumbing.plugins import tool

MAX_CELL_LENGTH = 500
MAX_CONNECT_TIMEOUT_SECONDS = 10
MAX_RENDERED_ROWS = 100
MAX_STATEMENT_TIMEOUT_MILLISECONDS = 15_000
MAX_TOTAL_OUTPUT_CHARS = 16_384
DEFAULT_SCHEMA = "public"
DEFAULT_ROW_LIMIT = MAX_RENDERED_ROWS
INLINE_TRUNCATION_MARKER = "...[truncated]"
OUTPUT_TRUNCATION_MARKER = "\n...[truncated]"
READ_ONLY_PREFIXES = ("SELECT",)


class StatementTimeoutError(SQLAlchemyError):
    """Raised when the required statement timeout cannot be applied."""


@tool(
    "db_query",
    description="Execute a read-only SQL query against a database",
    category="database",
    read_only=True,
)
def db_query(connection_url: str, query: str, limit: int = DEFAULT_ROW_LIMIT) -> str:
    """Execute a read-only SQL query and return a formatted table."""
    if not _is_read_only_query(query):
        return "Only read-only queries are allowed."

    row_limit = min(max(int(limit), 1), MAX_RENDERED_ROWS)

    try:
        with _open_connection(connection_url) as connection:
            _apply_statement_timeout(connection)
            result = connection.execute(text(query))
            columns = [str(column) for column in result.keys()]
            rows = result.mappings().fetchmany(row_limit + 1)
    except SQLAlchemyError as exc:
        return _format_sqlalchemy_error("Database query failed", exc)

    if not rows:
        return "Query returned no rows."

    truncated = len(rows) > row_limit
    visible_rows = rows[:row_limit]

    if truncated:
        lines = [f"Query returned at least {len(rows)} row(s)."]
    else:
        lines = [f"Query returned {len(visible_rows)} row(s)."]
    if columns:
        lines.append(f"Columns: {', '.join(columns)}")

    for index, row in enumerate(visible_rows, start=1):
        lines.append(f"- Row {index}: {_format_row(row, columns)}")

    if truncated:
        lines.append(f"Results truncated at {row_limit} row(s).")

    return _truncate_output("\n".join(lines))


@tool(
    "db_tables",
    description="List tables in a database",
    category="database",
    read_only=True,
)
def db_tables(connection_url: str, schema: str = DEFAULT_SCHEMA) -> str:
    """List tables in the requested schema."""
    try:
        with _open_connection(connection_url) as connection:
            _apply_statement_timeout(connection)
            engine = connection.engine
            inspector = inspect(connection)
            effective_schema = _normalize_schema(engine, schema)
            tables = sorted(inspector.get_table_names(schema=effective_schema))
    except SQLAlchemyError as exc:
        return _format_sqlalchemy_error("Database inspection failed", exc)

    if not tables:
        return f"No tables found in schema {schema}."

    lines = [f"Tables in schema {schema}:"]
    lines.extend(f"- {table}" for table in tables)
    return _truncate_output("\n".join(lines))


@tool(
    "db_table_schema",
    description="Describe columns and types for a table",
    category="database",
    read_only=True,
)
def db_table_schema(
    connection_url: str,
    table_name: str,
    schema: str = DEFAULT_SCHEMA,
) -> str:
    """Show columns, types, and constraints for a table."""
    try:
        with _open_connection(connection_url) as connection:
            _apply_statement_timeout(connection)
            engine = connection.engine
            inspector = inspect(connection)
            effective_schema = _normalize_schema(engine, schema)
            if not inspector.has_table(table_name, schema=effective_schema):
                return f"Table {table_name} not found in schema {schema}."

            columns = inspector.get_columns(table_name, schema=effective_schema)
            primary_key = inspector.get_pk_constraint(table_name, schema=effective_schema)
            unique_constraints = inspector.get_unique_constraints(
                table_name,
                schema=effective_schema,
            )
            foreign_keys = inspector.get_foreign_keys(table_name, schema=effective_schema)
    except SQLAlchemyError as exc:
        return _format_sqlalchemy_error("Database inspection failed", exc)

    lines = [f"Table schema for {table_name} in schema {schema}:", "Columns:"]
    pk_columns = set(primary_key.get("constrained_columns") or [])

    for column in columns:
        column_name = str(column["name"])
        type_name = str(column["type"])
        column_bits = [f"{column_name}: {type_name}"]

        if not bool(column.get("nullable", True)):
            column_bits.append("NOT NULL")

        default = column.get("default")
        if default is not None:
            column_bits.append(f"default={default}")

        if column_name in pk_columns:
            column_bits.append("PRIMARY KEY")

        lines.append(f"- {'; '.join(column_bits)}")

    if pk_columns:
        lines.append(f"Primary key: {', '.join(sorted(pk_columns))}")
    else:
        lines.append("Primary key: <none>")

    if unique_constraints:
        lines.append("Unique constraints:")
        for constraint in unique_constraints:
            columns_text = ", ".join(constraint.get("column_names") or [])
            name = constraint.get("name")
            if name:
                lines.append(f"- {name}: {columns_text}")
            else:
                lines.append(f"- {columns_text}")
    else:
        lines.append("Unique constraints: <none>")

    if foreign_keys:
        lines.append("Foreign keys:")
        for foreign_key in foreign_keys:
            constrained = ", ".join(foreign_key.get("constrained_columns") or [])
            referred_table = foreign_key.get("referred_table", "<unknown>")
            referred_columns = ", ".join(foreign_key.get("referred_columns") or [])
            lines.append(f"- {constrained} -> {referred_table}.{referred_columns}")
    else:
        lines.append("Foreign keys: <none>")

    return _truncate_output("\n".join(lines))


@tool(
    "db_connection_check",
    description="Test database connectivity and version",
    category="database",
    read_only=True,
)
def db_connection_check(connection_url: str) -> str:
    """Connect to the database and report a best-effort version string."""
    try:
        with _open_connection(connection_url) as connection:
            _apply_statement_timeout(connection)
            dialect_name = connection.dialect.name
            version_text = _fetch_version_text(connection)
    except SQLAlchemyError as exc:
        return _format_sqlalchemy_error("Database connection failed", exc)

    return _truncate_output(
        "\n".join(
            [
                "Connection successful.",
                f"Dialect: {dialect_name}",
                f"Version: {version_text}",
            ]
        )
    )


@contextmanager
def _open_connection(connection_url: str) -> Iterator[Connection]:
    engine = create_engine(_connection_url_with_connect_timeout(connection_url))
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()


def _is_read_only_query(query: str) -> bool:
    statement = query.lstrip()
    if not statement:
        return False
    prefix = statement.split(None, 1)[0].upper()
    return prefix in READ_ONLY_PREFIXES


def _connection_url_with_connect_timeout(connection_url: str) -> str:
    url = make_url(connection_url)
    if not url.drivername.startswith("postgresql"):
        return connection_url

    query = dict(url.query)
    query["connect_timeout"] = str(MAX_CONNECT_TIMEOUT_SECONDS)
    return url.set(query=query).render_as_string(hide_password=False)


def _apply_statement_timeout(connection: Connection) -> None:
    if not connection.dialect.name.startswith("postgresql"):
        return

    try:
        connection.exec_driver_sql(
            f"SET statement_timeout = {MAX_STATEMENT_TIMEOUT_MILLISECONDS}"
        )
    except SQLAlchemyError as exc:
        raise StatementTimeoutError("Unable to apply statement timeout.") from exc


def _normalize_schema(engine: Engine, schema: str) -> str | None:
    if engine.dialect.name == "sqlite" and schema == DEFAULT_SCHEMA:
        return None
    return schema


def _format_sqlalchemy_error(action: str, exc: SQLAlchemyError) -> str:
    return f"{action}: {_classify_sqlalchemy_error(exc)}"


def _classify_sqlalchemy_error(exc: SQLAlchemyError) -> str:
    type_names = [
        type(exc).__name__.lower(),
        type(getattr(exc, "orig", None)).__name__.lower(),
    ]

    combined = " ".join(type_names)
    if "timeout" in combined:
        return "timeout"
    if any(token in combined for token in ("auth", "credential", "login", "password")):
        return "authentication_failed"
    if any(token in combined for token in ("operationalerror", "connection", "disconnection")):
        return "connection_failed"
    return "unexpected_error"


def _format_row(row: Any, columns: Sequence[str]) -> str:
    if not columns:
        return "<no columns>"
    return ", ".join(f"{column}={_format_value(row.get(column))}" for column in columns)


def _format_value(value: Any) -> str:
    if value is None:
        return "<null>"
    if hasattr(value, "isoformat"):
        try:
            return _truncate_text(str(value.isoformat()), MAX_CELL_LENGTH, INLINE_TRUNCATION_MARKER)
        except TypeError:
            pass
    return _truncate_text(str(value), MAX_CELL_LENGTH, INLINE_TRUNCATION_MARKER)


def _truncate_output(body: str) -> str:
    return _truncate_text(body, MAX_TOTAL_OUTPUT_CHARS, OUTPUT_TRUNCATION_MARKER)


def _truncate_text(text_value: str, limit: int, marker: str) -> str:
    if len(text_value) <= limit:
        return text_value
    if limit <= len(marker):
        return text_value[:limit]
    return f"{text_value[: limit - len(marker)]}{marker}"


def _fetch_version_text(connection: Connection) -> str:
    dialect_name = connection.dialect.name

    try:
        if dialect_name == "sqlite":
            version = connection.exec_driver_sql("select sqlite_version()").scalar_one()
            return f"SQLite {version}"

        version = connection.exec_driver_sql("select version()").scalar_one()
        if version:
            return str(version)
    except SQLAlchemyError:
        pass

    server_version_info = getattr(connection.dialect, "server_version_info", None)
    if server_version_info:
        return ".".join(str(part) for part in server_version_info)

    return "<unknown>"
