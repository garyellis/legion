# Architecture Fit

How the SRE agent fleet maps to the existing `legion` layered architecture.

---

## What Already Works

The current codebase establishes patterns that the fleet buildout reuses directly.

| SRE Architecture Need | Current Codebase | Status |
|:-----------------------|:-----------------|:-------|
| Database persistence | `plumbing/database.py` — shared `Base`, `create_engine()`, SQLite + PostgreSQL | Ready |
| Config system | `plumbing/config/` — `LegionConfig` base, env var prefixes, `is_available()` | Ready |
| Domain models | `domain/incident.py` — Pydantic models with state machine | Pattern established |
| Repository pattern | ABC + InMemory + SQLite, engine injected, contract tests | Pattern established |
| Service layer with callbacks | `IncidentService` with `on_stale`/`on_resolved` injection | Pattern established |
| Slack surface with DI wiring | `slack/main.py` — config, engine, repos, service, handlers | Pattern established |
| AI chains (optional, graceful degradation) | `agents/chains/` — scribe, post-mortem; wrapped in try/except | Working |
| Dependency direction enforcement | `tests/test_dependency_direction.py` — catches violations | Enforced |

---

## What Needs to Be Built

### New Domain Entities

The SRE architecture introduces entities that cross multiple surfaces (CLI configures them, API dispatches through them, Slack triggers them). They belong in `domain/`.

- `Organization` — tenant boundary
- `ClusterGroup` — registered environment (dev-aks, prod-aks)
- `Agent` — running process with state (idle/busy/offline)
- `ChannelMapping` — Slack channel → cluster group, with mode (`alert` or `chat`)
- `FilterRule` — per-channel triage triggers (alert mode only)
- `PromptConfig` — system prompts, stack manifests per cluster group
- `Session` — conversational context pinned to one agent, spans multiple query jobs
- `Job` — unit of work (triage or query), optionally linked to a session and/or incident

See [Domain Model](./domain-model.md) for details.

### New Services

| Service | Responsibility |
|:--------|:---------------|
| `JobService` | Job lifecycle — create, assign, complete, fail, reassign |
| `DispatchService` | Channel → cluster group resolution, idle agent selection, queue drain; session-aware routing for chat channels |
| `SessionService` | Create/close sessions, get-or-create by thread, enforce agent pinning |
| `AgentConnectionManager` | Track WebSocket connections, agent state transitions, heartbeat |
| `FilterService` | Evaluate filter rules against incoming Slack messages (alert channels only) |

All follow the existing pattern: constructor-injected dependencies, callback-based outward communication, repository-backed persistence.

### New Surfaces

| Surface | What It Does |
|:--------|:-------------|
| `api/` | FastAPI app — CRUD routes, WebSocket handler, Slack Bolt sub-app |
| Agent process | New entry point `legion-agent` — WebSocket client, job executor, ReAct loop |

### New Infrastructure in `agents/`

The graph agent runtime (currently planned, not built):

- `graph.py` — ReAct loop engine
- `evaluator.py` — factual grounding check
- `tool_interceptor.py` — human-in-the-loop for destructive ops
- `context.py` — token estimation, rolling compaction
- `registry.py` — `@capability` → LangChain tool bridge

---

## Layer Mapping

Where each SRE component lands in the existing layer hierarchy:

```
              ┌────────┬────────┬────────┬─────────────┐
              │  cli/  │ slack/ │  api/  │ agent-proc/ │   SURFACES
              └───┬────┴───┬────┴───┬────┴──────┬──────┘
                  │    ┌───┴────────┴───┐       │
                  │    │    agents/     │───────-┘         AI RUNTIME (ReAct, chains)
                  │    └───────┬────────┘
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │   services/    │    │             JobService, DispatchService,
                  │    │               │    │             AgentConnectionManager
                  │    └───────┬────────┘    │
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │    domain/     │    │             Organization, ClusterGroup,
                  │    │               │    │             Agent, Job, ChannelMapping, ...
                  │    └───────┬────────┘    │
                  └────────────┼─────────────┘
                       ┌───────┴────────┐
                       │     core/      │                 kubectl wrapper, psql wrapper,
                       │               │                 prometheus client, etc.
                       └────────────────┘
         ┌─────────────────────────────────────────┐
         │            plumbing/                     │     Config, DB, logging (unchanged)
         └─────────────────────────────────────────┘
```

The data-plane agent process is a surface — it parses input (job payloads from WebSocket), calls logic (agents/ ReAct loop → core/ tools), and formats output (structured results back over WebSocket). It follows the same dependency rules as any other surface.

---

## The Slack Embedding Question

The SRE architecture describes "Central API + Slack Bolt" as a single process. Today `legion-slack` is standalone.

**Decision: Combined process** (see [Decisions](./decisions.md#1-slack-bolt-embedded-in-api)).

`api/main.py` hosts both FastAPI and Slack Bolt as ASGI sub-apps. This avoids duplicating the database connection, service instances, and WebSocket manager. The existing `legion-slack` entry point can be kept for simple deployments that don't need the fleet.
