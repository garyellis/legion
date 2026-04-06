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


class _FakeMessageRepo(_FakeRuntimeRepo):
    pass


class _FakeAuditEventRepo(_FakeRuntimeRepo):
    pass


class _FakeMessageService:
    def __init__(self, repo: object, **kwargs: object) -> None:
        self.repo = repo


class _FakeAuditService:
    def __init__(self, repo: object) -> None:
        self.repo = repo
        self.closed = False

    def close(self) -> None:
        self.closed = True


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
    monkeypatch.setattr(api_main, "SQLiteMessageRepository", _FakeMessageRepo)
    monkeypatch.setattr(api_main, "SQLiteAuditEventRepository", _FakeAuditEventRepo)
    monkeypatch.setattr(api_main, "MessageService", _FakeMessageService)
    monkeypatch.setattr(api_main, "AuditService", _FakeAuditService)


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


# ---------------------------------------------------------------------------
# App state contract test
# ---------------------------------------------------------------------------

# Expected attributes that must be present and non-None on app.state after
# startup.  When a new service or repo is added to the lifespan but not listed
# here the test will NOT catch the omission — it only catches the inverse:
# services listed here but missing from create_app().  Keep this list in sync
# with the lifespan wiring.
_EXPECTED_APP_STATE_ATTRIBUTES = [
    "fleet_repo",
    "job_repo",
    "session_repo",
    "agent_session_repo",
    "dispatch_service",
    "session_service",
    "filter_service",
    "connection_manager",
    "agent_delivery_service",
    "db_executor",
    "message_service",
    "audit_service",
]


def test_app_state_contract_all_services_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safety net: services implemented but not wired into create_app() are
    silently ignored by the WebSocket handler's getattr(..., None) pattern.
    This test ensures all expected services are present after app startup.

    If this test fails, a service or repository was added to the expected
    contract but is not being set on ``app.state`` during the lifespan.  Fix
    the lifespan in ``legion/api/main.py`` to wire the missing dependency.
    """
    validation_calls: list[object] = []
    _patch_runtime_deps(
        monkeypatch,
        db_url="sqlite:///:memory:",
        validation_calls=validation_calls,
    )

    app = create_app()
    with TestClient(app):
        missing = [
            attr
            for attr in _EXPECTED_APP_STATE_ATTRIBUTES
            if getattr(app.state, attr, None) is None
        ]

    assert not missing, (
        f"app.state is missing expected attributes after startup: {missing}. "
        f"Ensure create_app() sets these on app.state during the lifespan."
    )
