"""LangGraph ReAct runtime for Legion agent jobs."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypedDict, cast

from legion.agents.config import AgentConfig
from legion.agents.callbacks import TokenBudgetCallback
from legion.agents.context import JobContext
from legion.agents.evaluator import summarize_transcript
from legion.agents.exceptions import AgentError, LLMError
from legion.plumbing.plugins import get_tool_meta

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver

logger = logging.getLogger(__name__)

ToolCallable = Callable[..., object]


class ChatModel(Protocol):
    """Protocol for LLM chat models that support tool binding."""

    def bind_tools(self, tools: Any) -> Any: ...


def is_budget_exhausted(tokens_used: int, max_tokens: int) -> bool:
    """Single source of truth for budget exhaustion check."""
    return tokens_used >= max_tokens


@dataclass(frozen=True)
class ReactGraph:
    """Compiled LangGraph ReAct loop with its initial state factory."""

    compiled: Any  # CompiledStateGraph at runtime
    make_initial_state: Callable[..., dict[str, Any]]


def create_chat_model(config: AgentConfig) -> ChatModel:
    """Create a provider-specific chat model from *config*."""

    model_name = config.model_name.strip()
    if not model_name:
        raise AgentError("AGENT_MODEL_NAME must not be empty.")

    if _is_anthropic_model(model_name):
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise AgentError(
                "Anthropic models require the optional 'langchain-anthropic' dependency.",
            ) from exc

        resolved_name = model_name.partition("/")[2] if model_name.startswith("anthropic/") else model_name
        if not resolved_name:
            raise AgentError("Anthropic model names must include a concrete model id.")

        if not config.anthropic_api_key.get_secret_value():
            raise AgentError("Anthropic models require AGENT_ANTHROPIC_API_KEY.")
        return cast("ChatModel", ChatAnthropic(
            model=resolved_name,
            api_key=config.anthropic_api_key,
            max_tokens=config.max_completion_tokens,
            temperature=config.temperature,
        ))

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise AgentError(
            "OpenAI-compatible models require the optional 'langchain-openai' dependency.",
        ) from exc

    return cast("ChatModel", ChatOpenAI(
        model=model_name,
        base_url=config.model_base_url or None,
        api_key=(
            config.openai_api_key
            if config.openai_api_key.get_secret_value()
            else None
        ),
        max_completion_tokens=config.max_completion_tokens,
        temperature=config.temperature,
    ))


def build_react_graph(
    tools: Sequence[ToolCallable],
    config: AgentConfig,
    system_prompt: str,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    chat_model: ChatModel | None = None,
) -> ReactGraph:
    """Build a compiled ReAct graph for a Legion agent workload."""

    logger.info("building react graph with %d tools, model=%s", len(tools), config.model_name)

    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
        from langchain_core.tools import BaseTool, StructuredTool
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages
        from langgraph.prebuilt import ToolNode
    except ImportError as exc:
        raise AgentError(
            "LangGraph execution requires the optional agent dependencies.",
        ) from exc

    AgentState = TypedDict(
        "AgentState",
        {
            "messages": Annotated[list[Any], add_messages],
            "job_id": str,
            "max_tokens": int,
            "tokens_used": int,
            "budget_exhausted": bool,
            "result": str,
        },
    )

    structured_tools = _build_structured_tools(tools, StructuredTool)
    bound_model = _bind_tools(chat_model or create_chat_model(config), structured_tools)
    tool_node = ToolNode(cast(Sequence[BaseTool | Callable[..., Any]], structured_tools))

    def safe_tool_node(state: AgentState) -> dict[str, Any]:
        """Execute tools with error handling, returning failures as ToolMessages."""
        try:
            return tool_node(state)
        except Exception as exc:
            # Return error as a ToolMessage so the LLM can reason about the failure
            last_message = state["messages"][-1]
            error_messages = []
            for tc in getattr(last_message, "tool_calls", []):
                error_messages.append(
                    ToolMessage(
                        content=f"Tool error: {exc}",
                        name=tc["name"],
                        tool_call_id=tc["id"],
                    )
                )
            logger.warning(
                "tool_execution_error job=%s tool_calls=%d error=%s",
                state["job_id"],
                len(error_messages),
                str(exc),
            )
            if not error_messages:
                raise
            return {"messages": error_messages}

    def agent_node(state: AgentState) -> dict[str, Any]:
        ctx = JobContext(
            job_id=state["job_id"],
            max_tokens=state["max_tokens"],
            tokens_used=state["tokens_used"],
        )
        callback = TokenBudgetCallback(ctx)
        try:
            response = bound_model.invoke(
                state["messages"],
                config={"callbacks": [callback]},
            )
        except Exception as exc:
            raise LLMError(
                f"Agent generation failed: {exc}",
                model=config.model_name,
            ) from exc
        budget_exhausted = is_budget_exhausted(ctx.tokens_used, state["max_tokens"])
        logger.info(
            "agent_node job=%s tokens_used=%d/%d",
            state["job_id"], ctx.tokens_used, state["max_tokens"],
        )
        if budget_exhausted:
            logger.warning(
                "token_budget_exhausted job=%s tokens=%d/%d",
                state["job_id"], ctx.tokens_used, state["max_tokens"],
            )
        return {
            "messages": [response],
            "tokens_used": ctx.tokens_used,
            "budget_exhausted": budget_exhausted,
        }

    def evaluate_node(state: AgentState) -> dict[str, Any]:
        budget_exhausted = is_budget_exhausted(state["tokens_used"], state["max_tokens"])
        logger.info(
            "evaluate_node job=%s budget_exhausted=%s",
            state["job_id"], budget_exhausted,
        )
        return {
            "result": summarize_transcript(
                state["messages"],
                tokens_used=state["tokens_used"],
                budget_exhausted=budget_exhausted,
            ),
        }

    def route_after_agent(state: AgentState) -> str:
        if is_budget_exhausted(state["tokens_used"], state["max_tokens"]):
            destination = "evaluator"
        elif isinstance(state["messages"][-1], AIMessage) and state["messages"][-1].tool_calls:
            destination = "tools"
        else:
            destination = "evaluator"
        logger.debug("route_after_agent job=%s -> %s", state["job_id"], destination)
        return destination

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", safe_tool_node)
    graph.add_node("evaluator", evaluate_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"tools": "tools", "evaluator": "evaluator"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("evaluator", END)

    compiled_graph = graph.compile(checkpointer=checkpointer)

    def initial_state(*, job_id: str, payload: str, max_tokens: int | None = None) -> dict[str, Any]:
        return {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=payload),
            ],
            "job_id": job_id,
            "max_tokens": max_tokens or config.max_job_tokens,
            "tokens_used": 0,
            "budget_exhausted": False,
            "result": "",
        }

    return ReactGraph(compiled=compiled_graph, make_initial_state=initial_state)


def _is_anthropic_model(model_name: str) -> bool:
    return model_name.startswith("anthropic/") or model_name.startswith("claude-")


def _bind_tools(chat_model: ChatModel, tools: Sequence[object]) -> Any:
    bind_tools = getattr(chat_model, "bind_tools", None)
    if bind_tools is None:
        raise AgentError("Configured chat model does not support tool binding.")
    return bind_tools(tools)


def _build_structured_tools(
    tools: Sequence[ToolCallable],
    structured_tool_type: type[object],
) -> list[BaseTool]:
    structured_tools: list[BaseTool] = []
    from_function = getattr(structured_tool_type, "from_function")

    for tool_func in tools:
        meta = get_tool_meta(tool_func)
        name = meta.name if meta else tool_func.__name__
        if meta and meta.description:
            description = meta.description
        else:
            description = inspect.getdoc(tool_func) or f"Run the {name} tool."

        structured_tools.append(
            cast(
                "BaseTool",
                from_function(
                    tool_func,
                    name=name,
                    description=description,
                ),
            ),
        )

    return structured_tools
