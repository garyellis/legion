"""Health endpoint tests."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.services.fleet_repository import InMemoryFleetRepository
from legion.services.job_repository import InMemoryJobRepository
from legion.services.session_repository import InMemorySessionRepository


@pytest.fixture()
def fleet_repo():
    return InMemoryFleetRepository()


@pytest.fixture()
def app(fleet_repo):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=InMemoryJobRepository(),
        session_repo=InMemorySessionRepository(),
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
        broken_repo = MagicMock()
        broken_repo.list_orgs.side_effect = RuntimeError("connection refused")
        app = create_app(
            fleet_repo=broken_repo,
            job_repo=InMemoryJobRepository(),
            session_repo=InMemorySessionRepository(),
        )
        with TestClient(app) as client:
            resp = client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json() == {"detail": "not ready"}
