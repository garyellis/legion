"""Scribe chain — generates incident status updates from conversation history.

Uses LCEL (LangChain Expression Language) pipeline: prompt | llm | StrOutputParser.
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
You are an incident scribe. Given the recent Slack conversation from an \
incident channel, write a concise status update (3-5 bullet points) covering:
- What is currently happening
- What has been tried
- What the next steps are

Keep it factual and brief. Use bullet points."""


class ScribeChain:
    """LCEL chain that summarizes incident channel history."""

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

    def generate_update(self, history: ConversationHistory) -> str:
        """Summarize *history* into a status update string."""
        text = "\n".join(
            f"[{m.user}]: {m.text}" for m in reversed(history.messages) if m.text
        )
        if not text:
            return "No conversation history available."

        try:
            return self._chain.invoke({"history": text})
        except Exception as exc:
            raise LLMError(
                f"Scribe generation failed: {exc}",
                model=self._model_name,
            ) from exc
