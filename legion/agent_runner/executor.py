"""Deterministic B1 executor used by the standalone agent runner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

from legion.domain.protocol import (
    AuditEventMessage,
    JobDispatchMessage,
    JobProgressMessage,
    MessageEmitMessage,
)
from legion.plumbing.exceptions import LegionError

if TYPE_CHECKING:
    from legion.agents.config import AgentConfig
    from legion.agents.graph import ChatModel

logger = logging.getLogger(__name__)

SleepFn = Callable[[float], Awaitable[None]]

DEFAULT_JOB_SYSTEM_PROMPT = """\
You are Legion, an SRE investigation agent.
Use tools when they are needed to verify infrastructure state.
Prefer factual observations from tool output over guesses.
Return a concise operational conclusion."""


class ExecutionResult(BaseModel):
    """Successful executor output."""

    output: str


class JobEmitter(Protocol):
    """Callback interface for emitting real-time events during job execution."""

    async def emit_progress(self, step: str, detail: str = "", *, sequence: int | None = None) -> None: ...

    async def emit_message(self, message_type: str, content: str, metadata: dict[str, Any] | None = None) -> None: ...

    async def emit_audit_event(self, tool_name: str, tool_input: str, tool_output: str, duration_ms: int, *, sequence: int | None = None, error: str | None = None) -> None: ...


class NullJobEmitter:
    """No-op emitter for testing and the deterministic executor."""

    async def emit_progress(self, step: str, detail: str = "", *, sequence: int | None = None) -> None:
        pass

    async def emit_message(self, message_type: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        pass

    async def emit_audit_event(self, tool_name: str, tool_input: str, tool_output: str, duration_ms: int, *, sequence: int | None = None, error: str | None = None) -> None:
        pass


class WebSocketJobEmitter:
    """Concrete emitter that sends JSON over the agent's WebSocket."""

    def __init__(self, websocket: Any, job_id: str, send_lock: asyncio.Lock) -> None:
        self._websocket = websocket
        self._job_id = job_id
        self._send_lock = send_lock
        self._sequence = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    async def _send(self, message: BaseModel) -> None:
        async with self._send_lock:
            try:
                await self._websocket.send(message.model_dump_json())
            except Exception as exc:
                # Heuristic: detect connection-dead exceptions by class name to avoid
                # importing the websockets library here. Known matches: ConnectionClosed,
                # ConnectionClosedError, ConnectionClosedOK. This keeps the executor
                # framework-agnostic and testable.
                is_connection_dead = "close" in type(exc).__name__.lower() or "closed" in str(type(exc)).lower()
                logger.warning("websocket_send_failed job=%s msg=%s", self._job_id, type(message).__name__, exc_info=True)
                if is_connection_dead:
                    raise EmissionConnectionLost(
                        f"WebSocket connection lost during job {self._job_id}"
                    ) from exc

    async def emit_progress(self, step: str, detail: str = "", *, sequence: int | None = None) -> None:
        seq = self._next_sequence() if sequence is None else sequence
        msg = JobProgressMessage(job_id=self._job_id, step=step, detail=detail, sequence=seq)
        await self._send(msg)

    async def emit_message(self, message_type: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        msg = MessageEmitMessage(job_id=self._job_id, message_type=message_type, content=content, metadata=metadata or {})
        await self._send(msg)

    async def emit_audit_event(self, tool_name: str, tool_input: str, tool_output: str, duration_ms: int, *, sequence: int | None = None, error: str | None = None) -> None:
        seq = self._next_sequence() if sequence is None else sequence
        msg = AuditEventMessage(job_id=self._job_id, tool_name=tool_name, tool_input=tool_input, tool_output=tool_output, duration_ms=duration_ms, sequence=seq, error=error)
        await self._send(msg)


class _SyncEmitterBridge:
    """Adapts async JobEmitter to sync GraphEmitter for use inside graph nodes.

    Assumes LangGraph runs sync node functions on the event loop thread (not in
    a thread pool), so ``asyncio.get_running_loop()`` is available.  If a future
    LangGraph version moves sync nodes to threads, ``_fire`` must switch to
    ``asyncio.run_coroutine_threadsafe(coro, loop)``.
    """

    def __init__(self, emitter: JobEmitter) -> None:
        self._emitter = emitter
        self._sequence = 0
        self._pending: set[asyncio.Task[None]] = set()

    def _fire(self, coro: Coroutine[object, object, None]) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
            self._pending.add(task)
            task.add_done_callback(self._task_done)
        except RuntimeError:
            logger.debug("_SyncEmitterBridge: no running event loop, skipping emission")

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._pending.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("emitter task failed: %s", exc)

    def on_tool_start(self, tool_name: str, tool_input: str) -> None:
        self._sequence += 1
        self._fire(self._emitter.emit_progress(
            f"tool_start:{tool_name}", tool_input, sequence=self._sequence,
        ))

    def on_tool_end(self, tool_name: str, tool_input: str, tool_output: str, duration_ms: int, error: str | None = None) -> None:
        self._sequence += 1
        self._fire(self._emitter.emit_audit_event(
            tool_name, tool_input, tool_output, duration_ms, sequence=self._sequence, error=error,
        ))

    def on_agent_step(self, step: str, detail: str = "") -> None:
        self._sequence += 1
        self._fire(self._emitter.emit_progress(
            step, detail, sequence=self._sequence,
        ))

    async def flush(self) -> None:
        """Await all pending emission tasks to ensure telemetry is delivered."""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


class AgentExecutor(Protocol):
    """Port for deterministic and future production executors."""

    async def execute(self, job: JobDispatchMessage, emitter: JobEmitter) -> ExecutionResult: ...


class AgentExecutionError(LegionError):
    """Raised when the deterministic executor should fail a job."""


class EmissionConnectionLost(LegionError):
    """Raised when the emitter's WebSocket connection is dead."""

    retryable = True


class DeterministicAgentExecutor:
    """A predictable mock executor for Sprint B1 validation."""

    def __init__(
        self,
        *,
        execution_delay_seconds: float = 0.0,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._execution_delay_seconds = execution_delay_seconds
        self._sleep = sleep

    async def execute(self, job: JobDispatchMessage, emitter: JobEmitter) -> ExecutionResult:
        if self._execution_delay_seconds > 0:
            await self._sleep(self._execution_delay_seconds)

        if job.payload.startswith("fail:"):
            message = job.payload.partition(":")[2].strip() or "executor requested failure"
            raise AgentExecutionError(message)

        return ExecutionResult(
            output=f"mock-executor completed {job.job_type.value}: {job.payload}",
        )


class GraphExecutor:
    """LangGraph-backed executor for investigation jobs."""

    def __init__(
        self,
        *,
        tools: Sequence[Any],
        config: AgentConfig,
        chat_model: ChatModel | None = None,
    ) -> None:
        self._tools = list(tools)
        self._config = config
        self._chat_model = chat_model

    async def execute(self, job: JobDispatchMessage, emitter: JobEmitter) -> ExecutionResult:
        from legion.agents.graph import build_react_graph

        system_prompt = job.system_prompt or DEFAULT_JOB_SYSTEM_PROMPT
        bridge = _SyncEmitterBridge(emitter)

        graph = build_react_graph(
            self._tools,
            self._config,
            system_prompt,
            chat_model=self._chat_model,
            emitter=bridge,
        )

        payload = (
            f"Job type: {job.job_type.value}\n"
            f"Job id: {job.job_id}\n"
            f"Payload:\n{job.payload}"
        )
        state = graph.make_initial_state(
            job_id=job.job_id,
            payload=payload,
            max_tokens=job.max_job_tokens,
        )
        try:
            result = await graph.compiled.ainvoke(
                state,
                config={"recursion_limit": self._config.max_iterations},
            )
        except Exception as exc:
            await bridge.flush()
            raise AgentExecutionError(
                f"Graph execution failed for job {job.job_id}: {exc}",
            ) from exc
        await bridge.flush()
        return ExecutionResult(output=result["result"])
