"""Deterministic B1 executor used by the standalone agent runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from legion.agents.config import AgentConfig
from legion.agents.graph import ReactGraph, ToolCallable
from legion.agent_runner.models import JobDispatchMessage
from legion.plumbing.exceptions import LegionError

SleepFn = Callable[[float], Awaitable[None]]

DEFAULT_JOB_SYSTEM_PROMPT = """\
You are Legion, an SRE investigation agent.
Use tools when they are needed to verify infrastructure state.
Prefer factual observations from tool output over guesses.
Return a concise operational conclusion."""


class ExecutionResult(BaseModel):
    """Successful executor output."""

    output: str


class AgentExecutor(Protocol):
    """Port for deterministic and future production executors."""

    async def execute(self, job: JobDispatchMessage) -> ExecutionResult: ...


class AgentExecutionError(LegionError):
    """Raised when the deterministic executor should fail a job."""


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

    async def execute(self, job: JobDispatchMessage) -> ExecutionResult:
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
        tools: list[ToolCallable],
        config: AgentConfig,
        system_prompt: str = DEFAULT_JOB_SYSTEM_PROMPT,
        chat_model: object | None = None,
    ) -> None:
        from legion.agents.graph import build_react_graph

        self._config = config
        self._graph: ReactGraph = build_react_graph(
            tools,
            config,
            system_prompt,
            chat_model=chat_model,
        )

    async def execute(self, job: JobDispatchMessage) -> ExecutionResult:
        payload = (
            f"Job type: {job.job_type.value}\n"
            f"Job id: {job.job_id}\n"
            f"Payload:\n{job.payload}"
        )
        state = self._graph.make_initial_state(
            job_id=job.job_id,
            payload=payload,
            max_tokens=self._config.max_job_tokens,
        )
        result = await self._graph.compiled.ainvoke(
            state,
            config={"recursion_limit": self._config.max_iterations},
        )
        return ExecutionResult(output=result["result"])
