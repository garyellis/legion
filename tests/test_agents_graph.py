"""Tests for the B2 LangGraph ReAct loop.

The test suite replaces LangGraph primitives with lightweight fakes
(_FakeStateGraph, _FakeCompiledGraph, _FakeToolNode) to keep CI free of
LLM provider dependencies.  Known divergences from real LangGraph:

* ``add_messages`` reducer is not simulated — messages are appended without
  deduplication by message ID.
* ``_FakeCompiledGraph.ainvoke`` delegates to a synchronous ``invoke``, so
  async scheduling differences are not exercised.
* ``_FakeToolNode`` does not replicate ToolNode's built-in error formatting
  or retry logic.

Integration tests against real LangGraph are planned for Sprint C.
"""

from __future__ import annotations

import asyncio

import pytest
import sys
import types
from collections.abc import Callable

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import SecretStr

from legion.agents.config import AgentConfig
from legion.agents.exceptions import AgentError
from legion.agents.graph import ReactGraph, build_react_graph, create_chat_model
from legion.agent_runner.executor import GraphExecutor
from legion.domain.protocol import JobDispatchMessage
from legion.domain.job import JobType
from legion.plumbing.plugins import tool


class _FakeLLMResponse:
    def __init__(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.llm_output = {
            "token_usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }


class _FakeBoundModel:
    def __init__(
        self,
        responses: list[AIMessage],
        *,
        usages: list[tuple[int, int]],
    ) -> None:
        self._responses = list(responses)
        self._usages = list(usages)

    def invoke(self, _messages: list[object], config: dict[str, object] | None = None) -> AIMessage:
        callbacks = list((config or {}).get("callbacks", []))
        prompt_tokens, completion_tokens = self._usages.pop(0)
        response = self._responses.pop(0)
        usage = _FakeLLMResponse(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        for callback in callbacks:
            callback.on_llm_end(usage)
        return response


class _FakeChatModel:
    def __init__(
        self,
        responses: list[AIMessage],
        *,
        usages: list[tuple[int, int]],
    ) -> None:
        self._responses = responses
        self._usages = usages

    def bind_tools(self, tools: list[object]) -> _FakeBoundModel:  # noqa: ARG002
        return _FakeBoundModel(list(self._responses), usages=list(self._usages))


class _FakeCompiledGraph:
    def __init__(self, graph: "_FakeStateGraph") -> None:
        self._graph = graph

    async def ainvoke(
        self,
        state: dict[str, object],
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return self.invoke(state, config=config)

    def invoke(
        self,
        state: dict[str, object],
        config: dict[str, object] | None = None,
    ) -> dict[str, object]:
        current = self._graph.edges[self._graph.start_marker]
        merged = dict(state)
        steps = 0
        recursion_limit = int((config or {}).get("recursion_limit", 25))

        while current != self._graph.end_marker:
            steps += 1
            if steps > recursion_limit:
                raise RuntimeError("recursion limit exceeded")

            updates = self._graph.nodes[current](merged)
            merged = _merge_state(merged, updates)

            conditional = self._graph.conditional_edges.get(current)
            if conditional is not None:
                router, mapping = conditional
                current = mapping[router(merged)]
            else:
                current = self._graph.edges[current]

        return merged


class _FakeStateGraph:
    def __init__(self, _schema: object) -> None:
        self.nodes: dict[str, Callable[[dict[str, object]], dict[str, object]]] = {}
        self.edges: dict[str, str] = {}
        self.conditional_edges: dict[str, tuple[Callable[[dict[str, object]], str], dict[str, str]]] = {}
        self.start_marker = "START"
        self.end_marker = "END"

    def add_node(self, name: str, node: Callable[[dict[str, object]], dict[str, object]]) -> None:
        self.nodes[name] = node

    def add_edge(self, start: str, end: str) -> None:
        self.edges[start] = end

    def add_conditional_edges(
        self,
        name: str,
        router: Callable[[dict[str, object]], str],
        mapping: dict[str, str],
    ) -> None:
        self.conditional_edges[name] = (router, mapping)

    def compile(self, *, checkpointer: object | None = None) -> _FakeCompiledGraph:
        assert checkpointer is None
        return _FakeCompiledGraph(self)


class _FakeToolNode:
    def __init__(self, tools: list[object]) -> None:
        self._tools = {getattr(t, "name"): t for t in tools}

    def invoke(self, state: dict[str, object]) -> dict[str, object]:
        tool_messages: list[ToolMessage] = []
        last_message = state["messages"][-1]
        for tool_call in getattr(last_message, "tool_calls", []):
            matched_tool = self._tools[tool_call["name"]]
            result = matched_tool.invoke(tool_call["args"])
            tool_messages.append(
                ToolMessage(
                    content=result,
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                ),
            )
        return {"messages": tool_messages}

    __call__ = invoke


def _merge_state(
    state: dict[str, object],
    updates: dict[str, object] | None,
) -> dict[str, object]:
    merged = dict(state)
    for key, value in (updates or {}).items():
        if key == "messages":
            merged.setdefault("messages", [])
            merged["messages"] = [*merged["messages"], *value]
        else:
            merged[key] = value
    return merged


def _install_fake_langgraph(monkeypatch) -> None:
    langgraph_module = types.ModuleType("langgraph")
    graph_module = types.ModuleType("langgraph.graph")
    graph_message_module = types.ModuleType("langgraph.graph.message")
    prebuilt_module = types.ModuleType("langgraph.prebuilt")

    graph_module.START = "START"
    graph_module.END = "END"
    graph_module.StateGraph = _FakeStateGraph
    graph_message_module.add_messages = object()
    prebuilt_module.ToolNode = _FakeToolNode

    monkeypatch.setitem(sys.modules, "langgraph", langgraph_module)
    monkeypatch.setitem(sys.modules, "langgraph.graph", graph_module)
    monkeypatch.setitem(sys.modules, "langgraph.graph.message", graph_message_module)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", prebuilt_module)


def test_create_chat_model_routes_to_openai(monkeypatch) -> None:
    captured: dict[str, object] = {}
    module = types.ModuleType("langchain_openai")

    class FakeChatOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "langchain_openai", module)

    create_chat_model(
        AgentConfig(
            model_name="openai/gpt-oss-120b",
            model_base_url="http://localhost:11434/v1",
            max_completion_tokens=2048,
            temperature=0.2,
        ),
    )

    assert captured == {
        "model": "openai/gpt-oss-120b",
        "base_url": "http://localhost:11434/v1",
        "api_key": None,
        "max_completion_tokens": 2048,
        "temperature": 0.2,
    }


def test_create_chat_model_routes_to_anthropic(monkeypatch) -> None:
    captured: dict[str, object] = {}
    module = types.ModuleType("langchain_anthropic")

    class FakeChatAnthropic:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    module.ChatAnthropic = FakeChatAnthropic
    monkeypatch.setitem(sys.modules, "langchain_anthropic", module)

    create_chat_model(
        AgentConfig(
            model_name="anthropic/claude-3-7-sonnet",
            anthropic_api_key=SecretStr("anthropic-token"),
            max_completion_tokens=1024,
            temperature=0.1,
        ),
    )

    assert captured["model_name"] == "claude-3-7-sonnet"
    assert captured["max_tokens"] == 1024
    assert captured["temperature"] == 0.1
    assert captured["timeout"] is None
    assert captured["stop"] is None
    assert captured["api_key"].get_secret_value() == "anthropic-token"


def test_create_chat_model_requires_anthropic_api_key() -> None:
    with pytest.raises(AgentError, match="AGENT_ANTHROPIC_API_KEY"):
        create_chat_model(AgentConfig(model_name="anthropic/claude-3-7-sonnet"))


def test_build_react_graph_runs_tools_and_evaluates(monkeypatch) -> None:
    _install_fake_langgraph(monkeypatch)

    @tool("cluster_status", description="Check cluster status.", category="kubernetes")
    def cluster_status(namespace: str = "default") -> str:
        """Return the namespace status."""

        return f"namespace={namespace} status=healthy"

    graph = build_react_graph(
        [cluster_status],
        AgentConfig(),
        "Investigate cluster health.",
        chat_model=_FakeChatModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "cluster_status",
                            "args": {"namespace": "prod"},
                            "id": "call-1",
                            "type": "tool_call",
                        },
                    ],
                ),
                AIMessage(content="The cluster is healthy."),
            ],
            usages=[(9, 4), (5, 2)],
        ),
    )

    assert isinstance(graph, ReactGraph)
    result = asyncio.run(
        graph.compiled.ainvoke(
            graph.make_initial_state(
                job_id="job-1",
                payload="Check prod",
                max_tokens=50,
            ),
            config={"recursion_limit": 25},
        ),
    )

    assert "The cluster is healthy." in result["result"]
    assert "- cluster_status: namespace=prod status=healthy" in result["result"]
    assert result["tokens_used"] == 20


def test_build_react_graph_stops_when_budget_is_exhausted(monkeypatch) -> None:
    _install_fake_langgraph(monkeypatch)

    graph = build_react_graph(
        [],
        AgentConfig(),
        "Investigate budget use.",
        chat_model=_FakeChatModel(
            [AIMessage(content="Still working.")],
            usages=[(18, 5)],
        ),
    )

    assert isinstance(graph, ReactGraph)
    result = asyncio.run(
        graph.compiled.ainvoke(
            graph.make_initial_state(
                job_id="job-2",
                payload="Investigate",
                max_tokens=20,
            ),
            config={"recursion_limit": 25},
        ),
    )

    assert "Result status: partial" in result["result"]
    assert "Budget exhausted before the loop reached a natural stop." in result["result"]


def test_graph_executor_invokes_graph_with_job_payload(monkeypatch) -> None:
    _install_fake_langgraph(monkeypatch)

    @tool("echo_namespace", description="Echo a namespace.", category="test")
    def echo_namespace(namespace: str = "default") -> str:
        """Echo the provided namespace."""

        return f"namespace={namespace}"

    executor = GraphExecutor(
        tools=[echo_namespace],
        config=AgentConfig(max_job_tokens=40),
        chat_model=_FakeChatModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "echo_namespace",
                            "args": {"namespace": "prod"},
                            "id": "call-1",
                            "type": "tool_call",
                        },
                    ],
                ),
                AIMessage(content="Namespace captured."),
            ],
            usages=[(4, 2), (3, 1)],
        ),
    )

    from legion.agent_runner.executor import NullJobEmitter

    result = asyncio.run(
        executor.execute(
            JobDispatchMessage(
                type="job_dispatch",
                job_id="job-3",
                job_type=JobType.INVESTIGATE,
                payload="Inspect prod",
            ),
            NullJobEmitter(),
        ),
    )

    assert "Namespace captured." in result.output
    assert "- echo_namespace: namespace=prod" in result.output


def test_graph_emitter_receives_tool_events(monkeypatch) -> None:
    _install_fake_langgraph(monkeypatch)

    events: list[tuple[str, ...]] = []

    class RecordingEmitter:
        def on_tool_start(self, tool_name: str, tool_input: str) -> None:
            events.append(("tool_start", tool_name, tool_input))

        def on_tool_end(self, tool_name: str, tool_input: str, tool_output: str, duration_ms: int, error: str | None = None) -> None:
            events.append(("tool_end", tool_name, tool_output))

        def on_agent_step(self, step: str, detail: str = "") -> None:
            events.append(("agent_step", step))

    @tool("ping", description="Ping a host.", category="network")
    def ping(host: str = "localhost") -> str:
        return f"pong from {host}"

    graph = build_react_graph(
        [ping],
        AgentConfig(),
        "Test emitter.",
        chat_model=_FakeChatModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "ping", "args": {"host": "10.0.0.1"}, "id": "call-1", "type": "tool_call"},
                    ],
                ),
                AIMessage(content="Host is reachable."),
            ],
            usages=[(5, 3), (4, 2)],
        ),
        emitter=RecordingEmitter(),
    )

    result = asyncio.run(
        graph.compiled.ainvoke(
            graph.make_initial_state(job_id="emitter-test", payload="ping host", max_tokens=100),
            config={"recursion_limit": 25},
        ),
    )

    assert "Host is reachable." in result["result"]
    # Verify emitter received tool events
    tool_starts = [e for e in events if e[0] == "tool_start"]
    tool_ends = [e for e in events if e[0] == "tool_end"]
    agent_steps = [e for e in events if e[0] == "agent_step"]
    assert len(tool_starts) == 1
    assert tool_starts[0][1] == "ping"
    assert len(tool_ends) == 1
    assert "pong from 10.0.0.1" in tool_ends[0][2]
    assert len(agent_steps) >= 1


def test_graph_executor_wraps_exceptions_as_agent_execution_error(monkeypatch) -> None:
    _install_fake_langgraph(monkeypatch)

    class _ExplodingChatModel:
        def bind_tools(self, tools: list[object]) -> "_ExplodingBoundModel":
            return _ExplodingBoundModel()

    class _ExplodingBoundModel:
        def invoke(self, _messages: list[object], config: dict[str, object] | None = None) -> object:
            raise RuntimeError("LLM provider timeout")

    from legion.agent_runner.executor import AgentExecutionError, NullJobEmitter

    executor = GraphExecutor(
        tools=[],
        config=AgentConfig(),
        chat_model=_ExplodingChatModel(),
    )

    from legion.agents.exceptions import LLMError

    with pytest.raises(AgentExecutionError, match="job-err") as exc_info:
        asyncio.run(
            executor.execute(
                JobDispatchMessage(
                    type="job_dispatch",
                    job_id="job-err",
                    job_type=JobType.INVESTIGATE,
                    payload="Will fail",
                ),
                NullJobEmitter(),
            ),
        )
    assert isinstance(exc_info.value.__cause__, LLMError)
