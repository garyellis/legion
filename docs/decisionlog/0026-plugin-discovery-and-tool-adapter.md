# ADR-0026: Plugin discovery and tool adapter

**Status**: ACCEPTED
**Date**: 2026-04-05
**Author**: developer

## Context

B1 established the `@tool` decorator in `plumbing/plugins.py` and registered tool functions as entry points under `legion.tools` in `pyproject.toml`. Nothing discovers those entry points at runtime or adapts them for LangGraph's tool calling. The ReAct loop in `agents/graph.py` needs `StructuredTool` objects, and operators need visibility into installed plugins.

Two consumers need discovery: the agent runtime (needs `StructuredTool` objects with LangChain) and the CLI (needs `ToolMeta` only, no LangChain). These have different dependency requirements.

## Decision

Split discovery into two layers:

1. **`plumbing/plugins.py`** — `load_tool_callables()` uses `importlib.metadata.entry_points(group="legion.tools")` to discover and load tool functions. Returns `list[DiscoveredTool]` (func + ToolMeta + entry_point string). `discover_tool_metadata()` is a thin wrapper returning `list[ToolMeta]`. No LangChain dependency.

2. **`agents/tools.py`** — `discover_tools()` calls `load_tool_callables()` and wraps each function as `StructuredTool.from_function()`. LangChain import is deferred inside the function body (matching the pattern in `agents/chains/scribe.py`).

3. **`cli/commands/plugins.py`** — `plugins list` command calls `discover_tool_metadata()` from plumbing. No LangChain in the CLI import path.

Filtering (by category, read_only) lives in `load_tool_callables()` so both consumers can use it.

## Alternatives Considered

1. **All discovery in `agents/tools.py`** — rejected because the CLI would need to import from `agents/`, pulling in LangChain transitively. The CLI surface must not depend on agent-layer packages.

2. **Discovery as a service** — rejected because there is no business logic or state. Discovery is pure `importlib.metadata` lookup. A service layer would add indirection for a stateless read operation.

3. **Return raw callables from `discover_tools()` instead of `StructuredTool`** — rejected for this sprint. `build_react_graph()` currently wraps callables internally via `_build_structured_tools()`. The agent runner integration is a follow-up; adding a `discover_tool_callables()` convenience function then is trivial.

## Consequences

- Operators can see installed plugins via `legion-cli plugins list`.
- Agent runtime can discover tools dynamically instead of hardcoding imports.
- Third-party plugins installed via `pip install legion-tools-foo` are automatically discovered if they register `legion.tools` entry points.
- Follow-up: replace hardcoded tool list in `agent_runner/main.py` with `discover_tools()` or `load_tool_callables()`.
- Follow-up: Sprint D tool interceptor/policy enforcement can filter at the `DiscoveredTool` level before adaptation.

## References

- Feature brief: `docs/features/b2-plugin-discovery-and-tool-adapter.md`
- B1 tool decorator: `legion/plumbing/plugins.py`
- Entry points: `pyproject.toml` `[project.entry-points."legion.tools"]`
