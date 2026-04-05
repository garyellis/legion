# ADR-0025: Capability-based intra-group dispatch

**Status**: ACCEPTED
**Date**: 2026-04-05
**Author**: developer

## Context

`DispatchService.dispatch_pending()` routes jobs to an AgentGroup then picks any idle agent via `idle.pop(0)`. Agents within a group may have different capabilities -- one has `kubectl` access, another has `psql`, a third has both. Dispatching a database investigation to an agent without `psql` wastes a job cycle. Both `Agent.capabilities` and `Job.required_capabilities` fields already exist on the domain models and are persisted, but the matching logic in `dispatch_pending()` is absent.

## Decision

Layered routing: AgentGroup is the primary routing unit (explicit, operator-controlled). Capabilities are metadata on Agent used for **intra-group matching** by DispatchService.

Changes to `legion/services/dispatch_service.py`:
- `dispatch_pending()` filters idle agents by `set(job.required_capabilities).issubset(set(agent.capabilities))` before assignment
- Jobs with `required_capabilities=[]` match any idle agent (empty set is subset of everything)
- Jobs with capabilities that no idle agent can satisfy wait (not dispatched to an incapable agent)
- Telemetry counter `dispatch_capability_skips_total` (label: `agent_group_id`) increments once per job per dispatch cycle when no capable idle agent is found (monotonic counter, not per-distinct-job)
- `on_no_agents_available` callback now fires for both "no idle agents" and "idle agents exist but none have required capabilities". The callback receives only the Job — callers that need to distinguish the two cases should inspect idle agent state separately.

First-fit selection within the filtered set. No scoring or best-fit logic at this stage.

## Alternatives Considered

1. **AgentGroup-only routing (status quo)** -- wrong agent gets wrong job. A Kubernetes alert dispatched to an agent without kubectl wastes a job cycle and requires manual re-dispatch. Rejected because the capability fields already exist; only the matching logic is missing.

2. **Capability-only routing (no groups)** -- fully dynamic but removes operator control over agent assignment. Operators lose the ability to partition agents by team, environment, or trust boundary. Rejected because group-based routing serves an organizational purpose beyond capability matching.

## Consequences

- Enables targeted dispatch: k8s alerts go to agents with kubectl, database queries go to agents with psql.
- Jobs with unmet capability requirements wait rather than fail. Operators must ensure capable agents exist in each group.
- No cross-group dispatch. Capabilities refine within a group, never across groups.
- Future work: priority ordering among capable agents, dynamic capability registration.

## References

- `legion/domain/agent.py`: `Agent.capabilities` field
- `legion/domain/job.py`: `Job.required_capabilities` field
- `legion/services/dispatch_service.py`: `dispatch_pending()` method
