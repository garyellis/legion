# ADR-0016: LangGraph Runtime Dependency

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: developer

## Context

Sprint B2 replaces the mock executor with a real LangGraph ReAct loop in `agents/graph.py`. The agent needs to reason about infrastructure state, decide which tools to call, interpret results, and iterate until it has an answer. This is a StateGraph with conditional edges — the core abstraction LangGraph provides.

The project already depends on `langchain-openai>=0.3` and `langchain-core>=0.3` in the `[agents]` optional group. LangGraph is the orchestration layer that composes LLM calls and tool execution into a directed graph. Without it, we'd build a custom ReAct loop from scratch.

## Decision

Add `langgraph` to the `[project.optional-dependencies] agents` group with pin `>=0.3,<1`.

LangGraph provides `StateGraph`, `START`/`END` sentinels, conditional edges, and `ToolNode` — the exact primitives `agents/graph.py` needs. The `langgraph.prebuilt.create_react_agent` helper may simplify the initial implementation, but the custom `StateGraph` path is available when Decision 31's token budget requires hooking the loop control.

Checkpointer strategy is deferred to Sprint C/D. B2 uses `MemorySaver` (in-process) for chat sessions and no checkpointer for single-turn triage/investigate jobs. DB-backed checkpointing requires a custom `BaseCheckpointSaver` mapping LangGraph's thread keys to Legion's `session.id`/`job.id` — that complexity is not needed until persistent multi-turn conversations are required.

LangGraph stays confined to `agents/` only. It must not appear in `core/`, `domain/`, `services/`, or any surface. The architecture test (`test_dependency_direction.py`) already enforces this — `langgraph` is allowed in `agents/` and banned everywhere else.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `langgraph` |
| Version | `>=0.3,<1` |
| License | MIT |
| PyPI downloads/month | ~5M |
| Maintainers | LangChain Inc (5+ active) |
| Transitive deps | ~3 (langgraph-sdk, langgraph-checkpoint, langchain-core) |
| Last release | 2025 |
| Known CVEs | None |

## Alternatives Considered

1. **Custom ReAct loop with `langchain-core` only** — Build the reason-act-observe cycle manually using `ChatModel.bind_tools()` and a while loop. Rejected: reimplements conditional routing, state management, and tool dispatch that LangGraph already provides. The token budget hook (Decision 31) and future checkpointer integration are harder to retrofit onto a hand-rolled loop than onto a StateGraph with conditional edges.

2. **AutoGen / CrewAI** — Multi-agent orchestration frameworks. Rejected: Legion already has its own agent fleet orchestration (DispatchService, WebSocket protocol, job lifecycle). These frameworks would compete with Legion's control plane rather than complement it. LangGraph is a graph execution engine, not an orchestration platform — it stays inside the agent process.

3. **No framework — raw LLM API calls** — Call the chat completions API directly, parse tool calls from the response, execute tools, loop. Rejected: loses structured tool calling, forces manual JSON parsing of tool call responses, and makes the token budget circuit breaker harder to implement. The existing `chains/scribe.py` pattern uses LCEL for exactly this reason.

## Consequences

- `agents/graph.py` uses `StateGraph` for the ReAct loop with clean conditional edges for tool routing and budget enforcement.
- Added to `[agents]` optional group — not a required dependency. Surfaces that don't use agents don't pay the cost.
- `langgraph` pulls in `langgraph-checkpoint` even though B2 uses only `MemorySaver`. The checkpoint base classes are lightweight.
- Version pin `>=0.3,<1` covers the stable API. LangGraph's API has stabilized around the StateGraph/ToolNode pattern.
- Future: Sprint C/D adds a custom `BaseCheckpointSaver` for DB-backed persistence. This requires a separate ADR when the design is resolved.

## References

- Decision 12: Single LangGraph agent for chat and event processing
- Decision 31: Per-job token budget from Sprint B
- ADR-0006: httpx runtime dependency (similar evaluation pattern)
- Sprint B2 build phases: `docs/sre/planning/build-phases.md`
