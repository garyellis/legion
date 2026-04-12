"""Startup wiring tests for the Slack surface."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from legion.core.slack.config import SlackConfig
from legion.slack import main as slack_main


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, int]] = []
        self.started = False

    def add_job(self, func: Any, interval_seconds: int, id: str) -> None:
        self.jobs.append((id, interval_seconds))

    def start(self) -> None:
        self.started = True


class _FakeSocketModeHandler:
    def __init__(self, app: object, token: str) -> None:
        self.app = app
        self.token = token

    async def start_async(self) -> None:
        return None


class _FakeRuntimeRepo:
    def __init__(self, engine: object) -> None:
        self.engine = engine


class _FakeRuntimeIndex:
    def __init__(self, engine: object) -> None:
        self.engine = engine


class _FakeSessionLinkRepo:
    created_engines: list[object] = []

    def __init__(self, engine: object) -> None:
        self.engine = engine
        self.__class__.created_engines.append(engine)


def _patch_runtime_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_url: str,
    validation_calls: list[object],
) -> None:
    monkeypatch.setattr(
        slack_main,
        "DatabaseConfig",
        lambda: SimpleNamespace(url=db_url, echo=False, pool_pre_ping=True),
    )
    monkeypatch.setattr(slack_main, "create_engine", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        slack_main,
        "validate_database_schema_current",
        lambda engine: validation_calls.append(engine),
    )
    monkeypatch.setattr(slack_main, "SQLiteIncidentRepository", _FakeRuntimeRepo)
    monkeypatch.setattr(slack_main, "SQLiteSlackIncidentIndex", _FakeRuntimeIndex)
    monkeypatch.setattr(slack_main, "SQLiteSlackSessionLinkRepository", _FakeSessionLinkRepo)
    monkeypatch.setattr(slack_main, "SchedulerService", _FakeScheduler)
    monkeypatch.setattr(slack_main, "AsyncSocketModeHandler", _FakeSocketModeHandler)
    monkeypatch.setattr(slack_main, "load_commands", lambda app: None)
    monkeypatch.setattr(slack_main, "register_incident_handlers", lambda *args, **kwargs: None)


def test_start_socket_mode_uses_validation_helper_for_persistent_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    _FakeSessionLinkRepo.created_engines.clear()
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///legion.db",
        validation_calls=validation_calls,
    )

    asyncio.run(
        slack_main.start_socket_mode(
            SlackConfig(
                bot_token=SecretStr("xoxb-test"),
                app_token=SecretStr("xapp-test"),
            ),
        ),
    )

    assert len(validation_calls) == 1
    assert _FakeSessionLinkRepo.created_engines == validation_calls


def test_start_socket_mode_uses_validation_helper_for_in_memory_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    _FakeSessionLinkRepo.created_engines.clear()
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///:memory:",
        validation_calls=validation_calls,
    )

    asyncio.run(
        slack_main.start_socket_mode(
            SlackConfig(
                bot_token=SecretStr("xoxb-test"),
                app_token=SecretStr("xapp-test"),
            ),
        ),
    )

    assert len(validation_calls) == 1
    assert _FakeSessionLinkRepo.created_engines == validation_calls


def test_start_socket_mode_aborts_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeSessionLinkRepo.created_engines.clear()
    monkeypatch.setattr(
        slack_main,
        "DatabaseConfig",
        lambda: SimpleNamespace(url="sqlite:///legion.db", echo=False, pool_pre_ping=True),
    )
    monkeypatch.setattr(
        slack_main,
        "validate_database_schema_current",
        lambda engine: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(
            slack_main.start_socket_mode(
                SlackConfig(
                    bot_token=SecretStr("xoxb-test"),
                    app_token=SecretStr("xapp-test"),
                ),
            ),
        )


def test_start_socket_mode_registers_chat_routing_with_session_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    chat_registration_calls: list[dict[str, object]] = []
    _FakeSessionLinkRepo.created_engines.clear()
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///legion.db",
        validation_calls=validation_calls,
    )
    monkeypatch.setattr(
        slack_main,
        "register_chat_handlers",
        lambda *args, **kwargs: chat_registration_calls.append(kwargs),
    )

    asyncio.run(
        slack_main.start_socket_mode(
            SlackConfig(
                bot_token=SecretStr("xoxb-test"),
                app_token=SecretStr("xapp-test"),
            ),
        ),
    )

    assert len(chat_registration_calls) == 1
    registration = chat_registration_calls[0]
    session_service = registration["session_service"]
    assert session_service.session_link_repo is not None
    assert session_service.session_link_repo.__class__ is _FakeSessionLinkRepo
