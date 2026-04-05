"""End-to-end lifecycle tests for the agent runner surface."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest
import uvicorn

from legion.agent_runner.client import AgentRunnerClient
from legion.agent_runner.config import AgentRunnerConfig
from legion.agent_runner.executor import DeterministicAgentExecutor
from legion.api.config import APIConfig
from legion.api.main import create_app
from legion.domain.agent import AgentStatus
from legion.domain.agent_group import AgentGroup
from legion.domain.job import JobStatus
from legion.plumbing.database import create_all, create_engine
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository
from legion.core.fleet_api.async_client import AsyncFleetAPIClient

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


async def _wait_for(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 5.0,
    step_seconds: float = 0.01,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(step_seconds)
    raise AssertionError("Timed out waiting for test condition")


@pytest.fixture()
def _engine():
    engine = create_engine("sqlite:///:memory:")
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
def agent_session_repo(_engine):
    return SQLiteAgentSessionRepository(_engine)


@pytest.fixture()
def app(fleet_repo, job_repo, session_repo, agent_session_repo):
    return create_app(
        fleet_repo=fleet_repo,
        job_repo=job_repo,
        session_repo=session_repo,
        agent_session_repo=agent_session_repo,
        api_config=APIConfig(
            agent_session_token_ttl_seconds=90,
            agent_heartbeat_interval_seconds=1,
            log_format="JSON",
        ),
    )


def _seed_registration_token(
    fleet_repo: SQLiteFleetRepository,
    job_repo: SQLiteJobRepository,
    session_repo: SQLiteSessionRepository,
    agent_session_repo: SQLiteAgentSessionRepository,
) -> str:
    fleet_repo.save_agent_group(
        AgentGroup(
            id="ag-1",
            org_id=DEFAULT_ORG_ID,
            project_id=DEFAULT_PROJECT_ID,
            name="group",
            slug="group",
            environment="dev",
            provider="on-prem",
        ),
    )
    dispatch_service = DispatchService(
        fleet_repo,
        job_repo,
        session_repo,
        agent_session_repo,
    )
    rotation = dispatch_service.rotate_agent_group_registration_token("ag-1")
    return rotation.registration_token


class TestAgentRunnerLifecycle:
    def test_register_connect_execute_and_complete_job(
        self,
        app,
        fleet_repo,
        job_repo,
        session_repo,
        agent_session_repo,
        free_tcp_port: int,
    ) -> None:
        registration_token = _seed_registration_token(
            fleet_repo,
            job_repo,
            session_repo,
            agent_session_repo,
        )

        async def scenario() -> None:
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=free_tcp_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            server_task = asyncio.create_task(server.serve())

            try:
                await _wait_for(lambda: server.started)
                api_url = f"http://127.0.0.1:{free_tcp_port}"

                async with AsyncFleetAPIClient(api_url) as registration_client:
                    runner = AgentRunnerClient(
                        config=AgentRunnerConfig(
                            api_url=api_url,
                            registration_token=registration_token,
                            agent_name="runner-01",
                            capabilities=["kubernetes"],
                        ),
                        registration_client=registration_client,
                        executor=DeterministicAgentExecutor(execution_delay_seconds=0.2),
                        jitter=lambda _base: 0.0,
                    )
                    runner_task = asyncio.create_task(runner.run())

                    try:
                        await _wait_for(
                            lambda: (
                                len(fleet_repo.list_agents("ag-1")) == 1
                                and app.state.connection_manager.is_connected(
                                    fleet_repo.list_agents("ag-1")[0].id,
                                )
                            ),
                        )

                        async with httpx.AsyncClient(base_url=api_url, timeout=5.0) as client:
                            session_response = await client.post(
                                "/sessions/",
                                json={
                                    "org_id": DEFAULT_ORG_ID,
                                    "agent_group_id": "ag-1",
                                },
                            )
                            assert session_response.status_code == 201
                            session_id = session_response.json()["id"]

                            job_response = await client.post(
                                f"/sessions/{session_id}/messages",
                                json={"payload": "check pods"},
                            )
                            assert job_response.status_code == 201
                            job_id = job_response.json()["id"]

                        await _wait_for(
                            lambda: (
                                (job := job_repo.get_by_id(job_id)) is not None
                                and job.status == JobStatus.RUNNING
                            ),
                        )
                        await _wait_for(
                            lambda: (
                                (job := job_repo.get_by_id(job_id)) is not None
                                and job.status == JobStatus.COMPLETED
                            ),
                        )

                        completed_job = job_repo.get_by_id(job_id)
                        assert completed_job is not None
                        assert completed_job.result == "mock-executor completed QUERY: check pods"

                        registered_agent = fleet_repo.list_agents("ag-1")[0]
                        assert registered_agent.status == AgentStatus.IDLE
                        assert registered_agent.current_job_id is None
                    finally:
                        runner.request_shutdown()
                        await asyncio.wait_for(runner_task, timeout=5.0)
            finally:
                server.should_exit = True
                await asyncio.wait_for(server_task, timeout=5.0)

        asyncio.run(scenario())
