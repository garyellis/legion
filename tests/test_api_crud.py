"""CRUD route tests for the API surface."""

import pytest
from fastapi.testclient import TestClient

from legion.api.main import create_app
from legion.domain.agent import Agent, AgentStatus
from legion.domain.job import Job, JobStatus, JobType
from legion.domain.session import Session
from legion.plumbing.database import create_all, create_engine
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
    # Import Row classes by importing repo modules (already done above),
    # then create all tables.
    create_all(engine)
    return engine


@pytest.fixture()
def fleet_repo(_engine):
    return SQLiteFleetRepository(_engine)


@pytest.fixture()
def job_repo(_engine):
    return SQLiteJobRepository(_engine)


@pytest.fixture()
def session_repo(_engine):
    return SQLiteSessionRepository(_engine)


@pytest.fixture()
def app(fleet_repo, job_repo, session_repo):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        session_repo=session_repo,
    )


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

class TestOrganizations:
    def test_create(self, client):
        resp = client.post("/organizations/", json={"name": "Acme", "slug": "acme"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Acme"
        assert data["slug"] == "acme"
        assert "id" in data

    def test_list(self, client):
        client.post("/organizations/", json={"name": "Acme", "slug": "acme"})
        client.post("/organizations/", json={"name": "Beta", "slug": "beta"})
        resp = client.get("/organizations/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get(self, client):
        created = client.post("/organizations/", json={"name": "Acme", "slug": "acme"}).json()
        resp = client.get(f"/organizations/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Acme"

    def test_get_not_found(self, client):
        resp = client.get("/organizations/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# ClusterGroups
# ---------------------------------------------------------------------------

class TestClusterGroups:
    def _create_org(self, client):
        return client.post("/organizations/", json={"name": "Acme", "slug": "acme"}).json()

    def test_create(self, client):
        org = self._create_org(client)
        resp = client.post("/cluster-groups/", json={
            "org_id": org["id"], "name": "Prod", "slug": "prod",
            "environment": "production", "provider": "eks",
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Prod"

    def test_list_by_org(self, client):
        org = self._create_org(client)
        client.post("/cluster-groups/", json={
            "org_id": org["id"], "name": "Prod", "slug": "prod",
            "environment": "production", "provider": "eks",
        })
        resp = client.get(f"/cluster-groups/?org_id={org['id']}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client):
        org = self._create_org(client)
        created = client.post("/cluster-groups/", json={
            "org_id": org["id"], "name": "Prod", "slug": "prod",
            "environment": "production", "provider": "eks",
        }).json()
        resp = client.get(f"/cluster-groups/{created['id']}")
        assert resp.status_code == 200

    def test_get_not_found(self, client):
        resp = client.get("/cluster-groups/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class TestAgents:
    def test_list(self, client, fleet_repo):
        agent = Agent(cluster_group_id="cg-1", name="agent-01")
        fleet_repo.save_agent(agent)
        resp = client.get("/agents/?cluster_group_id=cg-1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client, fleet_repo):
        agent = Agent(cluster_group_id="cg-1", name="agent-01")
        fleet_repo.save_agent(agent)
        resp = client.get(f"/agents/{agent.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "agent-01"

    def test_get_not_found(self, client):
        resp = client.get("/agents/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# ChannelMappings
# ---------------------------------------------------------------------------

class TestChannelMappings:
    def test_create(self, client):
        resp = client.post("/channel-mappings/", json={
            "org_id": "org-1", "channel_id": "C123",
            "cluster_group_id": "cg-1", "mode": "ALERT",
        })
        assert resp.status_code == 201
        assert resp.json()["channel_id"] == "C123"

    def test_list(self, client):
        client.post("/channel-mappings/", json={
            "org_id": "org-1", "channel_id": "C123", "cluster_group_id": "cg-1",
        })
        resp = client.get("/channel-mappings/?org_id=org-1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client):
        created = client.post("/channel-mappings/", json={
            "org_id": "org-1", "channel_id": "C123", "cluster_group_id": "cg-1",
        }).json()
        resp = client.get(f"/channel-mappings/{created['id']}")
        assert resp.status_code == 200

    def test_delete(self, client):
        created = client.post("/channel-mappings/", json={
            "org_id": "org-1", "channel_id": "C123", "cluster_group_id": "cg-1",
        }).json()
        resp = client.delete(f"/channel-mappings/{created['id']}")
        assert resp.status_code == 204

    def test_delete_not_found(self, client):
        resp = client.delete("/channel-mappings/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# FilterRules
# ---------------------------------------------------------------------------

class TestFilterRules:
    def test_create(self, client):
        resp = client.post("/filter-rules/", json={
            "channel_mapping_id": "cm-1", "pattern": "ERROR.*timeout",
        })
        assert resp.status_code == 201
        assert resp.json()["pattern"] == "ERROR.*timeout"

    def test_create_invalid_regex(self, client):
        resp = client.post("/filter-rules/", json={
            "channel_mapping_id": "cm-1", "pattern": "[invalid",
        })
        assert resp.status_code == 422

    def test_list(self, client):
        client.post("/filter-rules/", json={
            "channel_mapping_id": "cm-1", "pattern": "ERROR",
        })
        resp = client.get("/filter-rules/?channel_mapping_id=cm-1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client):
        created = client.post("/filter-rules/", json={
            "channel_mapping_id": "cm-1", "pattern": "ERROR",
        }).json()
        resp = client.get(f"/filter-rules/{created['id']}")
        assert resp.status_code == 200

    def test_delete(self, client):
        created = client.post("/filter-rules/", json={
            "channel_mapping_id": "cm-1", "pattern": "ERROR",
        }).json()
        resp = client.delete(f"/filter-rules/{created['id']}")
        assert resp.status_code == 204


# ---------------------------------------------------------------------------
# PromptConfigs
# ---------------------------------------------------------------------------

class TestPromptConfigs:
    def test_upsert_create(self, client):
        resp = client.put("/prompt-configs/cg-1", json={
            "system_prompt": "You are an SRE.", "persona": "k8s expert",
        })
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "You are an SRE."

    def test_upsert_update(self, client):
        client.put("/prompt-configs/cg-1", json={"system_prompt": "v1"})
        resp = client.put("/prompt-configs/cg-1", json={"system_prompt": "v2"})
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "v2"

    def test_get(self, client):
        client.put("/prompt-configs/cg-1", json={"system_prompt": "hello"})
        resp = client.get("/prompt-configs/cg-1")
        assert resp.status_code == 200
        assert resp.json()["system_prompt"] == "hello"

    def test_get_not_found(self, client):
        resp = client.get("/prompt-configs/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class TestJobs:
    def test_list(self, client, job_repo):
        job = Job(org_id="org-1", cluster_group_id="cg-1", type=JobType.TRIAGE, payload="alert")
        job_repo.save(job)
        resp = client.get("/jobs/?cluster_group_id=cg-1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client, job_repo):
        job = Job(org_id="org-1", cluster_group_id="cg-1", type=JobType.TRIAGE, payload="alert")
        job_repo.save(job)
        resp = client.get(f"/jobs/{job.id}")
        assert resp.status_code == 200

    def test_get_not_found(self, client):
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class TestSessions:
    def test_create(self, client):
        resp = client.post("/sessions/", json={
            "org_id": "org-1", "cluster_group_id": "cg-1",
        })
        assert resp.status_code == 201
        assert resp.json()["status"] == "ACTIVE"

    def test_list(self, client):
        client.post("/sessions/", json={"org_id": "org-1", "cluster_group_id": "cg-1"})
        resp = client.get("/sessions/?cluster_group_id=cg-1")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_get(self, client):
        created = client.post("/sessions/", json={
            "org_id": "org-1", "cluster_group_id": "cg-1",
        }).json()
        resp = client.get(f"/sessions/{created['id']}")
        assert resp.status_code == 200

    def test_send_message(self, client):
        session = client.post("/sessions/", json={
            "org_id": "org-1", "cluster_group_id": "cg-1",
        }).json()
        resp = client.post(
            f"/sessions/{session['id']}/messages",
            json={"payload": "what is the pod status?"},
        )
        assert resp.status_code == 201
        assert resp.json()["type"] == "QUERY"
        assert resp.json()["status"] == "PENDING"

    def test_send_message_session_not_found(self, client):
        resp = client.post("/sessions/nope/messages", json={"payload": "hello"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_duplicate_error_returns_409(self, client, app):
        from legion.services.exceptions import DuplicateError

        @app.get("/test-duplicate")
        def _raise():
            raise DuplicateError("already exists")

        resp = client.get("/test-duplicate")
        assert resp.status_code == 409

    def test_filter_error_returns_422(self, client, app):
        from legion.services.exceptions import FilterError

        @app.get("/test-filter")
        def _raise():
            raise FilterError("bad regex")

        resp = client.get("/test-filter")
        assert resp.status_code == 422

    def test_dispatch_error_returns_404(self, client, app):
        from legion.services.exceptions import DispatchError

        @app.get("/test-dispatch")
        def _raise():
            raise DispatchError("not found")

        resp = client.get("/test-dispatch")
        assert resp.status_code == 404

    def test_generic_service_error_returns_500(self, client, app):
        from legion.services.exceptions import ServiceError

        @app.get("/test-service")
        def _raise():
            raise ServiceError("something broke")

        resp = client.get("/test-service")
        assert resp.status_code == 500
