"""Deterministic B1 executor used by the standalone agent runner."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from legion.agent_runner.models import JobDispatchMessage
from legion.plumbing.exceptions import LegionError

SleepFn = Callable[[float], Awaitable[None]]


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
