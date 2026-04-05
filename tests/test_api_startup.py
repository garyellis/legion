"""Startup wiring tests for the API surface."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from legion.api import main as api_main
from legion.api.main import create_app


class _FakeRuntimeRepo:
    def __init__(self, engine: object) -> None:
        self.engine = engine


class _FakeFleetRepo(_FakeRuntimeRepo):
    def __init__(self, engine: object) -> None:
        super().__init__(engine)
        self._orgs: dict[str, object] = {}
        self._projects: dict[str, object] = {}

    def get_org(self, org_id: str) -> object | None:
        return self._orgs.get(org_id)

    def save_org(self, org: object) -> None:
        self._orgs[getattr(org, "id")] = org

    def get_project(self, project_id: str) -> object | None:
        return self._projects.get(project_id)

    def save_project(self, project: object) -> None:
        self._projects[getattr(project, "id")] = project

    def list_orgs(self) -> list[object]:
        return list(self._orgs.values())


class _FakeJobRepo(_FakeRuntimeRepo):
    pass


class _FakeSessionRepo(_FakeRuntimeRepo):
    pass


class _FakeAgentSessionRepo(_FakeRuntimeRepo):
    pass


def _patch_runtime_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    db_url: str,
    validation_calls: list[object],
) -> None:
    monkeypatch.setattr(
        api_main,
        "DatabaseConfig",
        lambda: SimpleNamespace(url=db_url, echo=False, pool_pre_ping=True),
    )
    monkeypatch.setattr(api_main, "create_engine", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        api_main,
        "validate_database_schema_current",
        lambda engine: validation_calls.append(engine),
    )
    monkeypatch.setattr(api_main, "SQLiteFleetRepository", _FakeFleetRepo)
    monkeypatch.setattr(api_main, "SQLiteJobRepository", _FakeJobRepo)
    monkeypatch.setattr(api_main, "SQLiteSessionRepository", _FakeSessionRepo)
    monkeypatch.setattr(api_main, "SQLiteAgentSessionRepository", _FakeAgentSessionRepo)


def test_create_app_uses_validation_helper_for_persistent_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///legion.db",
        validation_calls=validation_calls,
    )

    app = create_app()
    with TestClient(app):
        pass

    assert len(validation_calls) == 1


def test_create_app_uses_validation_helper_for_in_memory_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation_calls: list[object] = []
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///:memory:",
        validation_calls=validation_calls,
    )

    app = create_app()
    with TestClient(app):
        pass

    assert len(validation_calls) == 1


def test_create_app_aborts_when_validation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_main,
        "DatabaseConfig",
        lambda: SimpleNamespace(url="sqlite:///legion.db", echo=False, pool_pre_ping=True),
    )
    monkeypatch.setattr(
        api_main,
        "validate_database_schema_current",
        lambda engine: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        with TestClient(create_app()):
            pass
