# ADR-0024: Custom StateGraph ReAct loop for B2 runtime

**Status**: PROPOSED
**Date**: 2026-04-05
**Author**: developer

## Context

Sprint B2 replaces the mock executor with a real ReAct loop in `legion/agents/graph.py`.
The brief requires three things at once:

1. The loop must be a LangGraph runtime, not a hand-written while loop.
2. The loop must stop deterministically when the per-job token budget is spent.
3. The loop must end in a factual evaluator step before returning to the runner.

LangGraph offers a prebuilt helper, `create_react_agent`, and the lower-level
`StateGraph` primitives. The helper is faster to wire initially, but B2 needs
control over loop routing and the final evaluator step. That control point is
the architectural choice for this milestone.

## Decision

Implement B2 with a custom `StateGraph` in `legion/agents/graph.py`.

The graph has three explicit nodes:

1. `agent` calls the chat model with bound tools.
2. `tools` executes tool calls through LangGraph's `ToolNode`.
3. `evaluator` deterministically summarizes the transcript and token usage.

Routing after the `agent` node is explicit:

- If the token budget is exhausted, route to `evaluator`.
- If the last AI message contains tool calls, route to `tools`.
- Otherwise route to `evaluator`.

This keeps LangGraph fully inside the `agents/` layer while giving Legion
direct control over the stop condition and the final result shape.

## Alternatives Considered

1. **Use LangGraph's `create_react_agent` helper**. Rejected because B2 needs
   deterministic control over when the loop exits and when the evaluator runs.
   The helper hides that routing behind the prebuilt agent abstraction, which
   makes token-budget enforcement and the final summary step less direct.
2. **Use a hand-written ReAct loop without LangGraph**. Rejected because ADR-0016
   already established LangGraph as the runtime abstraction for this milestone.
   A manual loop would duplicate tool routing and state handling that the graph
   library already provides.

## Consequences

- Enables deterministic loop control and a stable result contract for the runner.
- Costs a small amount of custom graph wiring in `agents/graph.py`.
- Leaves room for Sprint C/D to add a real checkpointer and richer evaluator
  behavior without replacing the graph topology.

## References

- `docs/features/b2-langgraph-react-loop.md`
- ADR-0016: LangGraph runtime dependency
- ADR-0017: langchain-anthropic LLM provider
