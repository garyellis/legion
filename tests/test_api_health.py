"""Health endpoint tests."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.plumbing.database import create_all, create_engine
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
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


class TestHealth:
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
        )
        with TestClient(app) as client:
            resp = client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json() == {"detail": "not ready"}
