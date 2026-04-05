"""Reconnect and disconnect tests for the agent runner surface."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from legion.agent_runner.client import AgentRunnerClient
from legion.agent_runner.config import AgentRunnerConfig
from legion.agent_runner.executor import DeterministicAgentExecutor, ExecutionResult
from legion.domain.protocol import JobDispatchMessage
from legion.core.fleet_api.models import (
    AgentConnectionConfig,
    AgentRegistrationResponse,
    AgentResponse,
)
from legion.domain.job import JobStatus, JobType
from legion.plumbing.database import create_all, create_engine
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SQLiteSessionRepository

def _registration_response(
    *,
    session_token: str,
    agent_id: str = "agent-01",
) -> AgentRegistrationResponse:
    now = datetime.now(timezone.utc)
    return AgentRegistrationResponse(
        agent=AgentResponse(
            id=agent_id,
            agent_group_id="ag-1",
            name="runner-01",
            status="IDLE",
            current_job_id=None,
            capabilities=["kubernetes"],
            last_heartbeat=None,
            created_at=now,
            updated_at=now,
        ),
        session_token=session_token,
        session_token_expires_at=now + timedelta(minutes=10),
        config=AgentConnectionConfig(
            heartbeat_interval_seconds=0,
            websocket_path=f"/ws/agents/{agent_id}",
        ),
    )


class FakeRegistrationClient:
    def __init__(self, responses: list[AgentRegistrationResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, list[str]]] = []

    async def register_agent(
        self,
        registration_token: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> AgentRegistrationResponse:
        self.calls.append((registration_token, name, capabilities or []))
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class FakeSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


class FakeWebSocket:
    def __init__(self, items: list[str | BaseException] | None = None) -> None:
        self._queue: asyncio.Queue[str | BaseException] = asyncio.Queue()
        for item in items or []:
            self._queue.put_nowait(item)
        self.sent_messages: list[str] = []
        self.close_codes: list[int] = []

    async def recv(self) -> str:
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        return item

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def close(self, code: int = 1000) -> None:
        self.close_codes.append(code)
        if self._queue.empty():
            self._queue.put_nowait(ConnectionClosedOK(Close(code, "closed"), None))


class FakeConnector:
    def __init__(self, results: list[FakeWebSocket | BaseException]) -> None:
        self._results = results
        self.calls: list[tuple[str, str]] = []
        self.connected = asyncio.Event()

    async def __call__(self, websocket_url: str, session_token: str) -> FakeWebSocket:
        self.calls.append((websocket_url, session_token))
        if len(self.calls) >= 2:
            self.connected.set()

        result = self._results[len(self.calls) - 1]
        if isinstance(result, BaseException):
            raise result
        return result


class ControlledExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, _job: JobDispatchMessage, _emitter=None):
        self.started.set()
        await self.release.wait()
        return ExecutionResult(output="controlled result")


class TestAgentRunnerReconnect:
    def test_transport_disconnect_reuses_cached_session_token(self) -> None:
        async def scenario() -> None:
            registration_client = FakeRegistrationClient(
                [_registration_response(session_token="session-1")],
            )
            sleep = FakeSleep()
            first_socket = FakeWebSocket(
                [ConnectionClosedError(Close(1006, "dropped"), None)],
            )
            second_socket = FakeWebSocket()
            connector = FakeConnector([first_socket, second_socket])
            runner = AgentRunnerClient(
                config=AgentRunnerConfig(
                    api_url="http://127.0.0.1:8000",
                    registration_token="registration-token",
                    agent_name="runner-01",
                    capabilities=["kubernetes"],
                ),
                registration_client=registration_client,
                executor=DeterministicAgentExecutor(),
                websocket_connector=connector,
                sleep=sleep,
                jitter=lambda _base: 0.0,
            )

            task = asyncio.create_task(runner.run())
            await asyncio.wait_for(connector.connected.wait(), timeout=5.0)
            runner.request_shutdown()
            await asyncio.wait_for(task, timeout=5.0)

            assert len(registration_client.calls) == 1
            assert connector.calls == [
                ("ws://127.0.0.1:8000/ws/agents/agent-01", "session-1"),
                ("ws://127.0.0.1:8000/ws/agents/agent-01", "session-1"),
            ]
            assert sleep.delays == [1.0]

        asyncio.run(scenario())

    def test_authentication_failure_forces_reregistration(self) -> None:
        async def scenario() -> None:
            registration_client = FakeRegistrationClient(
                [
                    _registration_response(session_token="session-1"),
                    _registration_response(session_token="session-2"),
                ],
            )
            sleep = FakeSleep()
            auth_failure = InvalidStatus(
                Response(403, "Forbidden", Headers(), b""),
            )
            second_socket = FakeWebSocket()
            connector = FakeConnector([auth_failure, second_socket])
            runner = AgentRunnerClient(
                config=AgentRunnerConfig(
                    api_url="http://127.0.0.1:8000",
                    registration_token="registration-token",
                    agent_name="runner-01",
                    capabilities=["kubernetes"],
                ),
                registration_client=registration_client,
                executor=DeterministicAgentExecutor(),
                websocket_connector=connector,
                sleep=sleep,
                jitter=lambda _base: 0.0,
            )

            task = asyncio.create_task(runner.run())
            await asyncio.wait_for(connector.connected.wait(), timeout=5.0)
            runner.request_shutdown()
            await asyncio.wait_for(task, timeout=5.0)

            assert len(registration_client.calls) == 2
            assert connector.calls == [
                ("ws://127.0.0.1:8000/ws/agents/agent-01", "session-1"),
                ("ws://127.0.0.1:8000/ws/agents/agent-01", "session-2"),
            ]
            assert sleep.delays == [1.0]

        asyncio.run(scenario())

    def test_unexpected_connector_error_fails_fast(self) -> None:
        async def scenario() -> None:
            registration_client = FakeRegistrationClient(
                [_registration_response(session_token="session-1")],
            )
            sleep = FakeSleep()
            connector = FakeConnector([RuntimeError("connector bug")])
            runner = AgentRunnerClient(
                config=AgentRunnerConfig(
                    api_url="http://127.0.0.1:8000",
                    registration_token="registration-token",
                    agent_name="runner-01",
                    capabilities=["kubernetes"],
                ),
                registration_client=registration_client,
                executor=DeterministicAgentExecutor(),
                websocket_connector=connector,
                sleep=sleep,
                jitter=lambda _base: 0.0,
            )

            with pytest.raises(RuntimeError, match="connector bug"):
                await runner.run()

            assert sleep.delays == []

        asyncio.run(scenario())

    def test_shutdown_waits_for_inflight_job_to_finish(self) -> None:
        async def scenario() -> None:
            registration_client = FakeRegistrationClient(
                [_registration_response(session_token="session-1")],
            )
            websocket = FakeWebSocket([
                json.dumps({
                    "type": "job_dispatch",
                    "job_id": "job-1",
                    "job_type": "QUERY",
                    "payload": "check pods",
                }),
            ])
            connector = FakeConnector([websocket])
            executor = ControlledExecutor()
            runner = AgentRunnerClient(
                config=AgentRunnerConfig(
                    api_url="http://127.0.0.1:8000",
                    registration_token="registration-token",
                    agent_name="runner-01",
                    capabilities=["kubernetes"],
                ),
                registration_client=registration_client,
                executor=executor,
                websocket_connector=connector,
                jitter=lambda _base: 0.0,
            )

            task = asyncio.create_task(runner.run())
            await asyncio.wait_for(executor.started.wait(), timeout=5.0)
            runner.request_shutdown()
            await asyncio.sleep(0)
            assert not task.done()

            executor.release.set()
            await asyncio.wait_for(task, timeout=5.0)

            sent_types = [json.loads(message)["type"] for message in websocket.sent_messages]
            assert sent_types == ["job_started", "job_result"]
            assert websocket.close_codes[-1] == 1000

        asyncio.run(scenario())


class TestReassignDisconnected:
    def test_reassign_disconnected_reverts_running_jobs(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        create_all(engine)
        fleet_repo = SQLiteFleetRepository(engine)
        job_repo = SQLiteJobRepository(engine)
        session_repo = SQLiteSessionRepository(engine)
        agent_session_repo = SQLiteAgentSessionRepository(engine)
        service = DispatchService(
            fleet_repo,
            job_repo,
            session_repo,
            agent_session_repo,
        )

        agent = service.register_agent("ag-1", "agent-01")
        job = service.create_job("org-1", "ag-1", JobType.QUERY, "check pods")
        service.dispatch_pending("ag-1")
        dispatched_job = job_repo.get_by_id(job.id)
        assert dispatched_job is not None
        dispatched_job.start()
        job_repo.save(dispatched_job)

        reverted = service.reassign_disconnected(agent.id)

        assert len(reverted) == 1
        assert reverted[0].status == JobStatus.PENDING
        assert reverted[0].agent_id is None
