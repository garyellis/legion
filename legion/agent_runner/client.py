"""Async control-plane client loop for the B1 agent runner."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ValidationError
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from legion.agent_runner.config import AgentRunnerConfig
from legion.agent_runner.executor import AgentExecutionError, AgentExecutor
from legion.agent_runner.models import (
    HeartbeatMessage,
    JobDispatchMessage,
    JobFailedMessage,
    JobResultMessage,
    JobStartedMessage,
    RegisteredAgentSession,
)
from legion.core.fleet_api.client import FleetAPIError
from legion.core.fleet_api.models import AgentRegistrationResponse

logger = logging.getLogger(__name__)

AUTHENTICATION_CLOSE_CODES = frozenset({4001, 4003})
AUTHENTICATION_STATUS_CODES = frozenset({401, 403, 4001, 4003})

SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[float], float]
WebSocketConnector = Callable[[str, str], Awaitable["RunnerWebSocket"]]


class AgentRegistrationClient(Protocol):
    """Registration client used by the runner surface."""

    async def register_agent(
        self,
        registration_token: str,
        name: str,
        capabilities: list[str] | None = None,
    ) -> AgentRegistrationResponse: ...


class RunnerWebSocket(Protocol):
    """Minimal WebSocket protocol surface used by the runner loop."""

    async def recv(self) -> str: ...
    async def send(self, message: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


async def connect_websocket(websocket_url: str, session_token: str) -> RunnerWebSocket:
    """Open a websocket connection using bearer auth and app-level heartbeats."""

    return cast(
        RunnerWebSocket,
        await websocket_connect(
            websocket_url,
            additional_headers={"Authorization": f"Bearer {session_token}"},
            ping_interval=None,
        ),
    )


def default_jitter(base_delay_seconds: float) -> float:
    """Return a small positive jitter to avoid synchronized reconnects."""

    return random.uniform(0.0, min(1.0, base_delay_seconds))


class AgentRunnerClient:
    """Long-running agent process that registers, connects, and executes jobs."""

    def __init__(
        self,
        *,
        config: AgentRunnerConfig,
        registration_client: AgentRegistrationClient,
        executor: AgentExecutor,
        websocket_connector: WebSocketConnector = connect_websocket,
        sleep: SleepFn = asyncio.sleep,
        jitter: JitterFn = default_jitter,
    ) -> None:
        self._config = config
        self._registration_client = registration_client
        self._executor = executor
        self._websocket_connector = websocket_connector
        self._sleep = sleep
        self._jitter = jitter
        self._stop_requested = asyncio.Event()
        self._send_lock = asyncio.Lock()
        self._current_websocket: RunnerWebSocket | None = None
        self._current_job_id: str | None = None
        self._cached_session: RegisteredAgentSession | None = None

    def request_shutdown(self) -> None:
        """Ask the runner to stop after any in-flight job completes."""

        self._stop_requested.set()
        if self._current_job_id is None:
            self._schedule_close_current_websocket()

    async def run(self) -> None:
        """Run the agent loop until shutdown is requested."""

        logger.info("Agent runner starting for %s", self._config.agent_name)
        reconnect_attempt = 0

        while not self._stop_requested.is_set():
            try:
                session = await self._get_or_register_session()
                await self._run_session(session)
                reconnect_attempt = 0
            except Exception as exc:
                if self._stop_requested.is_set():
                    break

                if not self._should_retry(exc):
                    raise

                if self._is_authentication_failure(exc):
                    self._cached_session = None
                    logger.warning(
                        "Session authentication failed for %s; re-registering",
                        self._config.agent_name,
                    )
                else:
                    logger.warning(
                        "Agent runner connection dropped for %s: %s",
                        self._config.agent_name,
                        exc,
                    )

                reconnect_attempt += 1
                delay = self._compute_reconnect_delay(reconnect_attempt)
                logger.info(
                    "Reconnecting agent %s in %.2f seconds",
                    self._config.agent_name,
                    delay,
                )
                await self._sleep(delay)

        logger.info("Agent runner stopped for %s", self._config.agent_name)

    async def _get_or_register_session(self) -> RegisteredAgentSession:
        if self._cached_session is not None and not self._cached_session.is_expired():
            return self._cached_session

        logger.info("Registering agent %s with control plane", self._config.agent_name)
        registration = await self._registration_client.register_agent(
            self._config.registration_token,
            self._config.agent_name,
            self._config.capabilities,
        )
        self._cached_session = RegisteredAgentSession.from_registration(
            api_url=self._config.api_url,
            registration=registration,
        )
        logger.info(
            "Agent %s registered with id %s",
            self._config.agent_name,
            self._cached_session.agent_id,
        )
        return self._cached_session

    async def _run_session(self, session: RegisteredAgentSession) -> None:
        websocket = await self._websocket_connector(
            session.websocket_url,
            session.session_token,
        )
        self._current_websocket = websocket
        logger.info("Connected agent %s to %s", session.agent_id, session.websocket_url)
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(websocket, session.heartbeat_interval_seconds),
        )

        try:
            while not self._stop_requested.is_set():
                raw_message = await websocket.recv()
                message = self._parse_job_dispatch(raw_message)
                if message is None:
                    continue
                await self._handle_job_dispatch(websocket, message)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            self._current_websocket = None
            await self._safe_close(websocket)

    def _parse_job_dispatch(self, raw_message: str) -> JobDispatchMessage | None:
        try:
            return JobDispatchMessage.model_validate_json(raw_message)
        except ValidationError:
            logger.warning("Ignoring unsupported control-plane message: %s", raw_message)
            return None

    async def _handle_job_dispatch(
        self,
        websocket: RunnerWebSocket,
        message: JobDispatchMessage,
    ) -> None:
        self._current_job_id = message.job_id
        await self._send_message(websocket, JobStartedMessage(job_id=message.job_id))
        logger.info("Started job %s (%s)", message.job_id, message.job_type.value)

        try:
            result = await self._executor.execute(message)
        except AgentExecutionError as exc:
            await self._send_message(
                websocket,
                JobFailedMessage(job_id=message.job_id, error=str(exc)),
            )
            logger.info("Job %s failed deterministically: %s", message.job_id, exc)
        except Exception as exc:
            await self._send_message(
                websocket,
                JobFailedMessage(job_id=message.job_id, error=str(exc)),
            )
            logger.exception("Job %s failed unexpectedly", message.job_id)
        else:
            await self._send_message(
                websocket,
                JobResultMessage(job_id=message.job_id, result=result.output),
            )
            logger.info("Completed job %s", message.job_id)
        finally:
            self._current_job_id = None
            if self._stop_requested.is_set():
                await self._close_current_websocket()

    async def _heartbeat_loop(
        self,
        websocket: RunnerWebSocket,
        heartbeat_interval_seconds: int,
    ) -> None:
        if heartbeat_interval_seconds <= 0:
            return

        while not self._stop_requested.is_set():
            await self._sleep(heartbeat_interval_seconds)
            if self._stop_requested.is_set():
                return
            try:
                await self._send_message(websocket, HeartbeatMessage())
            except ConnectionClosed:
                return

    async def _send_message(self, websocket: RunnerWebSocket, message: BaseModel) -> None:
        payload = message.model_dump_json()
        async with self._send_lock:
            await websocket.send(payload)

    def _compute_reconnect_delay(self, attempt: int) -> float:
        base_delay = min(float(2 ** max(attempt - 1, 0)), 300.0)
        return min(300.0, base_delay + max(0.0, self._jitter(base_delay)))

    def _is_authentication_failure(self, exc: Exception) -> bool:
        if isinstance(exc, InvalidStatus):
            return exc.response.status_code in AUTHENTICATION_STATUS_CODES
        if isinstance(exc, ConnectionClosed):
            close_code = exc.rcvd.code if exc.rcvd is not None else None
            return close_code in AUTHENTICATION_CLOSE_CODES
        return False

    def _should_retry(self, exc: Exception) -> bool:
        if self._is_authentication_failure(exc):
            return True
        if isinstance(exc, FleetAPIError):
            return exc.retryable
        if isinstance(exc, InvalidStatus):
            return exc.response.status_code in {429, 502, 503, 504}
        if isinstance(exc, (ConnectionClosed, httpx.HTTPError, OSError, asyncio.TimeoutError)):
            return True
        return False

    def _schedule_close_current_websocket(self) -> None:
        if self._current_websocket is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._close_current_websocket())

    async def _close_current_websocket(self) -> None:
        if self._current_websocket is None:
            return
        await self._safe_close(self._current_websocket)

    async def _safe_close(self, websocket: RunnerWebSocket) -> None:
        with suppress(ConnectionClosed):
            await websocket.close(code=1000)
