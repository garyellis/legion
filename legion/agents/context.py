"""Execution context and token budget tracking for agent jobs."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class JobContext:
    """Mutable per-job execution budget."""

    job_id: str
    max_tokens: int = 32_768
    tokens_used: int = 0

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulate token usage from a single LLM call."""
        self.tokens_used += max(prompt_tokens, 0) + max(completion_tokens, 0)


def extract_token_usage(response: object) -> tuple[int, int]:
    """Extract prompt and completion counts from LangChain response metadata."""
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        prompt_tokens = _as_int(
            llm_output.get("prompt_tokens")
            or llm_output.get("input_tokens")
        )
        completion_tokens = _as_int(
            llm_output.get("completion_tokens")
            or llm_output.get("output_tokens")
        )
        if prompt_tokens or completion_tokens:
            return prompt_tokens, completion_tokens

        usage = llm_output.get("token_usage")
        if isinstance(usage, dict):
            prompt_tokens = _as_int(
                usage.get("prompt_tokens") or usage.get("input_tokens")
            )
            completion_tokens = _as_int(
                usage.get("completion_tokens") or usage.get("output_tokens")
            )
            if prompt_tokens or completion_tokens:
                return prompt_tokens, completion_tokens
    generations = getattr(response, "generations", [])
    for generation_batch in generations:
        if isinstance(generation_batch, list):
            candidates = generation_batch
        else:
            candidates = [generation_batch]
        for generation in candidates:
            usage_metadata = getattr(
                getattr(generation, "message", None),
                "usage_metadata",
                None,
            )
            if not isinstance(usage_metadata, dict):
                continue
            prompt_tokens = _as_int(
                usage_metadata.get("input_tokens") or usage_metadata.get("prompt_tokens")
            )
            completion_tokens = _as_int(
                usage_metadata.get("output_tokens")
                or usage_metadata.get("completion_tokens")
            )
            if prompt_tokens or completion_tokens:
                return prompt_tokens, completion_tokens

    # If we got here with a structured response, token metadata was unparseable.
    if getattr(response, "llm_output", None) is not None or generations:
        logger.warning(
            "token_usage_unparseable: response had metadata but no token counts extracted"
        )
    return 0, 0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
