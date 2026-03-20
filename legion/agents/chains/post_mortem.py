"""Post-mortem chain — generates PIR reports from incident conversation history.

Uses LCEL pipeline: prompt | llm | StrOutputParser.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from legion.agents.config import AgentConfig
from legion.agents.exceptions import LLMError

if TYPE_CHECKING:
    from legion.core.slack.models import ConversationHistory

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a post-incident report writer. Given the full Slack conversation \
from an incident channel, generate a structured Post-Incident Report (PIR) in \
Markdown with these sections:

# Post-Incident Report
## Summary
## Timeline
## Root Cause
## Impact
## Action Items

Be thorough but concise and professional. Extract facts from the conversation. do not scare or exagerate."""


class PostMortemChain:
    """LCEL chain that generates a PIR from incident channel history."""

    def __init__(self, config: AgentConfig) -> None:
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=config.model_name,
            base_url=config.model_base_url,
            api_key=config.openai_api_key.get_secret_value(),  # type: ignore[arg-type]
            max_completion_tokens=config.max_completion_tokens,
            temperature=config.temperature,
        )
        prompt = ChatPromptTemplate.from_messages(
            [("system", _SYSTEM_PROMPT), ("human", "{history}")]
        )
        self._chain = prompt | llm | StrOutputParser()
        self._model_name = config.model_name

    def generate_report(self, history: ConversationHistory) -> str:
        """Generate a PIR from *history*."""
        text = "\n".join(
            f"[{m.user}]: {m.text}" for m in reversed(history.messages) if m.text
        )
        if not text:
            return "# Post-Incident Report\n\nNo conversation history available."

        try:
            return self._chain.invoke({"history": text})
        except Exception as exc:
            raise LLMError(
                f"PIR generation failed: {exc}",
                model=self._model_name,
            ) from exc
