"""Tests for token budget tracking in the agent layer."""

from __future__ import annotations

from legion.agents.callbacks import TokenBudgetCallback
from legion.agents.context import JobContext


class _ResponseWithLLMOutput:
    def __init__(self, token_usage: dict[str, int]) -> None:
        self.llm_output = {"token_usage": token_usage}


class _MessageWithUsage:
    def __init__(self, usage: dict[str, int]) -> None:
        self.usage_metadata = usage


class _Generation:
    def __init__(self, message: object) -> None:
        self.message = message


class _ResponseWithGenerations:
    def __init__(self, usage: dict[str, int]) -> None:
        self.generations = [[_Generation(_MessageWithUsage(usage))]]


def test_job_context_accumulates_tokens() -> None:
    context = JobContext(job_id="job-1", max_tokens=100)

    context.record_usage(5, 7)
    assert context.tokens_used == 12

    context.record_usage(10, 3)
    assert context.tokens_used == 25


def test_token_budget_callback_reads_llm_output_usage() -> None:
    context = JobContext(job_id="job-1", max_tokens=20)
    callback = TokenBudgetCallback(context)

    callback.on_llm_end(
        _ResponseWithLLMOutput({"prompt_tokens": 8, "completion_tokens": 5}),
    )

    assert context.tokens_used == 13


def test_token_budget_callback_reads_usage_metadata_fallback() -> None:
    context = JobContext(job_id="job-1", max_tokens=10)
    callback = TokenBudgetCallback(context)

    callback.on_llm_end(
        _ResponseWithGenerations({"input_tokens": 7, "output_tokens": 5}),
    )

    assert context.tokens_used == 12
