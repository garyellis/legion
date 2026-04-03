"""API key authentication middleware tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.plumbing.database import create_all, create_engine
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository

API_KEY = "test-secret"


def _make_repos():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return {
        "fleet_repo": SQLiteFleetRepository(engine),
        "job_repo": SQLiteJobRepository(engine),
        "session_repo": SQLiteSessionRepository(engine),
    }


def _make_client(*, api_key: str = "") -> TestClient:
    app = create_app(**_make_repos(), api_key=api_key)
    return TestClient(app)


class TestAPIKeyAuth:
    """Verify X-API-Key middleware behaviour."""

    def test_no_key_configured_allows_request(self):
        with _make_client() as client:
            resp = client.get("/organizations/")
            assert resp.status_code == 200

    def test_key_configured_no_header_returns_401(self):
        with _make_client(api_key=API_KEY) as client:
            resp = client.get("/organizations/")
            assert resp.status_code == 401
            assert resp.json() == {"detail": "Invalid or missing API key"}

    def test_key_configured_wrong_key_returns_401(self):
        with _make_client(api_key=API_KEY) as client:
            resp = client.get("/organizations/", headers={"X-API-Key": "wrong-key"})
            assert resp.status_code == 401
            assert resp.json() == {"detail": "Invalid or missing API key"}

    def test_key_configured_correct_key_returns_200(self):
        with _make_client(api_key=API_KEY) as client:
            resp = client.get("/organizations/", headers={"X-API-Key": API_KEY})
            assert resp.status_code == 200

    def test_health_bypasses_auth(self):
        with _make_client(api_key=API_KEY) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_health_ready_bypasses_auth(self):
        with _make_client(api_key=API_KEY) as client:
            resp = client.get("/health/ready")
            assert resp.status_code == 200
