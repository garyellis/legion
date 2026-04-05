"""LangChain callback handler for token budget tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from legion.agents.context import JobContext

if TYPE_CHECKING:
    from langchain_core.outputs import LLMResult


class TokenBudgetCallback:
    """Record token usage from chat model responses onto a job context.

    Implements the LangChain BaseCallbackHandler interface via duck typing
    to avoid a hard module-level dependency on langchain_core.
    """

    raise_error = True

    def __init__(self, context: JobContext) -> None:
        self._context = context

    def on_llm_end(
        self,
        response: LLMResult,
        **_kwargs: Any,
    ) -> None:
        from legion.agents.context import extract_token_usage

        prompt_tokens, completion_tokens = extract_token_usage(response)
        self._context.record_usage(prompt_tokens, completion_tokens)
