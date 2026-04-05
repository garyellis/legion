"""Health endpoint tests."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from legion.api.config import APIConfig
from legion.api.main import create_app
from legion.plumbing.database import create_all, create_engine
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return engine


@pytest.fixture()
def fleet_repo(_engine):
    return SQLiteFleetRepository(_engine)


@pytest.fixture()
def app(fleet_repo, _engine):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=SQLiteJobRepository(_engine),
        session_repo=SQLiteSessionRepository(_engine),
        agent_session_repo=SQLiteAgentSessionRepository(_engine),
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


class TestHealth:
    def test_create_app_requires_all_repos_when_injecting(self, fleet_repo, _engine):
        with pytest.raises(
            ValueError,
            match="fleet_repo, job_repo, session_repo, and agent_session_repo must all be provided together",
        ):
            create_app(
                fleet_repo=fleet_repo,
                job_repo=SQLiteJobRepository(_engine),
            )

    def test_create_app_rejects_partial_injection_when_token_repo_is_missing(self, fleet_repo, _engine):
        with pytest.raises(
            ValueError,
            match="fleet_repo, job_repo, session_repo, and agent_session_repo must all be provided together",
        ):
            create_app(
                fleet_repo=fleet_repo,
                job_repo=SQLiteJobRepository(_engine),
                session_repo=SQLiteSessionRepository(_engine),
            )

    def test_create_app_rejects_token_repo_without_other_repos(self, _engine):
        with pytest.raises(
            ValueError,
            match="fleet_repo, job_repo, session_repo, and agent_session_repo must all be provided together",
        ):
            create_app(
                agent_session_repo=SQLiteAgentSessionRepository(_engine),
            )

    def test_liveness(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readiness(self, client):
        resp = client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_readiness_db_failure(self):
        engine = create_engine("sqlite:///:memory:")
        create_all(engine)
        broken_repo = MagicMock()
        broken_repo.list_orgs.side_effect = RuntimeError("connection refused")
        app = create_app(
            fleet_repo=broken_repo,
            job_repo=SQLiteJobRepository(engine),
            session_repo=SQLiteSessionRepository(engine),
            agent_session_repo=SQLiteAgentSessionRepository(engine),
            api_config=APIConfig(),
        )
        with TestClient(app) as client:
            resp = client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json() == {"detail": "not ready"}
