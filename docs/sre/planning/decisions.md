# Architectural Decisions

> Every design decision with problem statement, options considered, choice, and rationale. This is the record of why the system is built the way it is.
>
> **Format**: Each decision follows: Problem → Options → Decision → Rationale. Add new decisions to the end with the next sequence number.

---

## 1. Domain Entities in `domain/`, Not in Services

**Problem**: Where do fleet entities (Organization, AgentGroup, Agent, Job, etc.) live?

**Decision**: Pydantic models in `domain/`, ORM rows in `services/`.

**Rationale**: These entities are referenced by multiple surfaces (CLI configures them, API serves them, Slack triggers through them, agents execute them). They cross core boundaries. This follows the existing pattern — `Incident` is in `domain/`, `IncidentRow` is in `services/repository.py`. The domain stays persistence-free; the service layer handles mapping.

---

## 2. One Repository Per Aggregate, Not Per Entity

**Problem**: The fleet has 7+ entities. One ABC + InMemory + SQLite per entity would be tedious for simple CRUD patterns.

**Decision**: Group simple CRUD entities into shared repositories. Complex query patterns get dedicated repositories.

**Approach**:
- **`FleetRepository`** — combined: Organization, AgentGroup, Agent, ChannelMapping, FilterRule, PromptConfig
- **`JobRepository`** — dedicated: complex queries (pending by group, reassign, status transitions)
- **`SessionRepository`** — dedicated: thread-based lookup, agent pinning

If the combined repository becomes unwieldy, split it.

---

## 3. Session-Based Conversations with Agent Affinity

**Problem**: Operators need interactive conversations with agents. How to maintain context across turns?

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| One-shot query jobs | Simple, no new concepts | No context, agent can't refer to previous answers |
| Session-based conversations | Agent retains context, natural chat UX | New entity, agent affinity routing |

**Decision**: Sessions. A `Session` groups related messages into a conversation pinned to one agent. When a message arrives in a chat channel, the dispatcher checks for an active session in that Slack thread. If one exists, it routes to the same agent. If not, it creates a new session and assigns an idle agent.

**Channel modes**: `ChannelMapping` has a `mode` field — `ALERT` (filter rules evaluate messages, triage jobs created) or `CHAT` (every message becomes a query job routed through sessions).

**Surface portability**: Sessions are domain/service concepts. Same API calls work from Slack, CLI, admin UI.

---

## 4. Every Job Has a Session

**Problem**: One-shot triage jobs and watchdog-generated jobs don't have explicit sessions. This makes them invisible and non-interactive.

**Decision**: `session_id` is required on every job. `DispatchService.create_job()` auto-creates a session when one is not provided.

**Rationale**:
- Every job is observable — see what an agent is doing via its session
- Any session can be connected to interactively — attach to an in-progress triage session
- Sessions are the universal unit of agent interaction

---

## 5. AgentGroup (Replacing ClusterGroup)

**Problem**: "ClusterGroup" implies k8s clusters only. What if you want an agent group for a database fleet, an observability platform, or a single-purpose specialist?

**Decision**: Rename to `AgentGroup`. The `environment` and `provider` fields become optional metadata, not required structure.

**Rationale**: Enables limitless configurability — map an agent group to any purpose, give it a unique prompt, assign agents with the right credentials.

---

## 6. PostgreSQL for Production, SQLite for Dev

**Problem**: The fleet API needs concurrent access from WebSocket connections, Slack handlers, and CRUD routes.

**Decision**: PostgreSQL in production, SQLite for local dev and testing.

**Rationale**: SQLite's write lock is a bottleneck for concurrent access. `plumbing/database.py` handles both dialects. `psycopg[binary]` already in `pyproject.toml`. Repository contract tests run against in-memory SQLite.

---

## 7. Slack Bolt Embedded in API

**Problem**: The SRE architecture requires the API to receive Slack events, dispatch jobs over WebSocket, and post results to Slack. Should Slack be a separate process?

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Combined process | One DB pool, one set of services, no network hop | Larger process |
| Slack as API client | Independent scaling | Duplicated DB, extra latency, sync complexity |

**Decision**: Combined. `api/main.py` hosts both FastAPI and Slack Bolt as ASGI sub-apps. Shared services and database.

**Preserving simplicity**: `legion-slack` standalone entry point kept for single-node deployments that don't need the fleet.

---

## 8. CLI Always Goes Through the API

**Problem**: Should the CLI talk to the database directly or call the API?

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Direct DB access | Faster to build, no API dependency | Bypasses validation, split-brain risk |
| API client only | Single writer, consistent validation | Requires running API |

**Decision**: API client only. The API is the single writer to the database. The CLI dependency on a running API is a feature — if the API is down, operators should know.

---

## 9. WebSocket for Delivery, Database for Durability

**Problem**: Jobs could be dispatched purely in-memory (fast) or persisted first (durable).

**Decision**: Jobs are always written to the database before dispatch. WebSocket is just a push notification channel.

**Rationale**: If WebSocket drops, the job stays `assigned` in the DB. Heartbeat timeout → agent offline → job reverts to `pending` → reassigned. No work lost. Even at 1000 clusters, job volume is within relational DB limits.

---

## 10. Filter Rules Evaluated Server-Side

**Problem**: When a message arrives in a mapped alert channel, who evaluates whether it triggers a triage job?

**Decision**: The API evaluates filter rules from its database.

**Rationale**: No config sync to agents. Changes take effect immediately. Agents stay stateless — they receive jobs, not raw messages. The `FilterService` is a pure function.

---

## 11. Agent Process as a Surface

**Problem**: Where does the data-plane agent fit in the layer model?

**Decision**: It's a surface. Same pattern as CLI and Slack: parse input (job payloads), call logic (ReAct loop → tools), format output (results back over WebSocket). Same dependency rules.

---

## 12. Single LangGraph Agent for Chat and Event Processing

**Problem**: Should chat sessions and triage jobs use separate graphs or one parameterized graph?

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Separate graphs | Each optimized for workload | Duplicated tool wiring |
| Single graph, parameterized | One set of tools, consistent behavior | Slightly more complex entry config |

**Decision**: Single graph. The ReAct loop is identical. What differs is entry configuration:

| | Chat | Event Processing |
|:--|:-----|:-----------------|
| Checkpointer | Loads prior conversation (session.id) | Starts fresh (job.id) |
| System prompt | Conversational persona from PromptConfig | Alert-analysis prompt |
| Streaming | Required (tokens to Slack/UI) | Progress updates (optional) |
| Turns | Multi-turn, session-pinned | Single-turn, stateless |

LangGraph stays in `agents/` only. Does not leak into services, domain, or core.

---

## 13. Knowledge Layer: Git + Markdown First

**Problem**: Agents need runbooks, stack manifests, known alert patterns, post-incident reports.

**Decision**: Git repository of markdown files. No vector database initially.

**Rationale**: Version control, human readability, PR-based review, zero infrastructure. Agents clone on boot, pull at job start. Repo URL is part of agent group config.

Vector index layered on later for semantic search when the knowledge base grows. Markdown stays the source of truth; embeddings are a derived index.

---

## 14. Watchdog Agents as External Observers

**Problem**: An agent inside a cluster can't report "the cluster is down."

**Decision**: Watchdog agents run outside clusters using the same agent graph and control plane but with different tools. They can self-generate triage jobs.

**Key differences**:
- **Tools**: HTTP probes, DNS, TLS inspection, synthetic transactions (no kubectl, no cluster creds)
- **Job flow**: Watchdogs push — they create TRIAGE jobs via the API. Inside agents pull.
- **Deployment**: Anywhere with network access. No cluster credentials.

A watchdog is just another agent registered to an agent group. The control plane doesn't distinguish.

---

## 15. Inter-Agent Queries with Security Boundaries

**Problem**: An agent triaging in one cluster may need info from another cluster without having its credentials.

**Decision**: Agents query other agents through the control plane. Cross-agent queries governed by an allowlist policy.

**Mechanism**: Inter-agent query is a `core/fleet/` tool that creates a `QUERY` job via the API targeting another agent group.

**Security**: `QueryPolicy` defines permitted `(source, target)` agent group pairs. **Deny by default** — every cross-agent path must be explicitly opened.

**Cycle prevention**: Jobs carry a `depth` field (default 0). Incremented on each inter-agent query. Rejected beyond configurable max (default 3).

**Audit**: Every inter-agent query is a normal Job — fully tracked in the database.

---

## 16. Agent Parallelism: One Job at a Time

**Problem**: Should agents handle multiple jobs concurrently?

**Decision**: Each agent process handles one job at a time. The control plane schedules at the job level.

**Rationale**:
- Strong ownership — clear diagnostics, predictable token budget
- Agent may perform async internal operations within that one job
- Agent may spawn child tasks/subagents as part of the job
- Horizontal scaling: add more agents, not more threads
- Control plane handles scheduling, not the agent

---

## 17. Redis as the Messaging Tier

**Problem**: WebSocket is ephemeral. Process restart loses in-flight messages.

**Decision**: Redis Streams for at-least-once delivery. **Required for all fleet deployments**, including local dev.

**Boundaries**:
- **Redis**: Message queuing, pub/sub, replay buffer, ephemeral agent status cache, audit event buffering, activity stream fan-out
- **PostgreSQL**: Durable state (jobs, sessions, config, LLM usage, audit)
- Control plane drains Redis → PostgreSQL asynchronously

**Why not optional**: Running without Redis means dev uses in-process messaging while production uses Redis — two completely different code paths. Bugs in the Redis path only surface in production. Redis in `docker compose up` costs ~5MB RAM and ensures dev/prod parity for the entire messaging layer. The only deployment that skips Redis is `legion-slack` standalone (no fleet, no dispatch pipeline).

---

## 18. Agent Registration via API Key

**Problem**: How do agents authenticate and register with the control plane?

**Decision**: Create API key on the control plane. Agent boots with the key and agent group ID, connects to WebSocket, authenticates. Agents do not need to be pre-registered — the API key is enough.

**Deregistration**: Explicit (delete via control plane) or implicit (heartbeat timeout).

---

## 19. Preserve `legion-slack` for Simple Deployments

**Problem**: Not every deployment needs the full fleet.

**Decision**: Keep the standalone `legion-slack` entry point alongside `legion-api`.

- `legion-slack` — standalone incident bot (SQLite, no fleet)
- `legion-api` — combined API + Slack + fleet (PostgreSQL, WebSocket, agents)

Same services, same domain models. Different wiring.

---

## 20. Design Methodology

**Decision**: Every design question is resolved with: problem statement, options considered, decision, trade-offs, rationale.

**Rationale**: The system has distributed state, security boundaries, and multi-surface coordination. Vibe coding works for simple apps; this system requires explicit architecture. The design phase precedes the build phase for each area. AI agents and human contributors both need unambiguous constraints.

---

## 21. Drop InMemory Repository Implementations

**Problem**: Every repository has ABC → InMemory → SQLite (three layers). Each repository method is implemented twice. Contract tests exist solely to verify both implementations behave the same. InMemory uses Python dict/list semantics that can diverge from SQL semantics in subtle ways (ordering, null handling, cascading deletes).

**Decision**: One SQLAlchemy implementation per repository ABC. Tests use `sqlite:///:memory:`. Drop all `InMemory*Repository` classes.

**Rationale**: `sqlite:///:memory:` IS in-memory. It's milliseconds to spin up, completely isolated per test, and tests the actual ORM and SQL code — not a fake approximation. The InMemory implementations doubled maintenance, could mask real SQL bugs, and required contract tests that served no purpose beyond verifying parity between two implementations. The ABC stays as interface documentation; the SQLAlchemy implementation satisfies it.

---

## 22. Tool Registry + Adapter Pattern

**Problem**: Tools (e.g., "check pod status", "run DNS lookup") need to be callable from agents (LangChain ReAct loop), Slack commands, CLI, API endpoints, and a future plugin system. Where does the tool interface live?

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| LangChain `@tool` on core functions | Zero custom code, automatic schema generation | core/ imports langchain_core — violates layer rule. Every non-agent caller transitionally depends on LangChain. Plugin system must understand LangChain's tool interface. |
| Registry + adapter | core/ stays framework-free. Plugin system inspects plain functions. Swapping LangChain only touches adapter. | More wiring code in agents/tools.py (one line per tool). |

**Decision**: Core functions stay plain Python in `core/<domain>/`. Type hints define parameter schemas, docstrings define descriptions. An adapter layer in `agents/tools.py` wraps them as LangChain `StructuredTool` via `StructuredTool.from_function()`. Other surfaces import from `core/` directly.

**Rationale**: The core function IS the tool contract. Putting `@tool` from LangChain on core functions violates the dependency direction rule — `core/` must not know about AI frameworks. The adapter is mechanical (one line per tool) and creates a clean seam for the future plugin system, which can inspect the same plain functions to generate capability schemas without any LangChain dependency.

---

## 23. Vertical Sprint Delivery Over Horizontal Phases

**Problem**: The original 10-phase plan completes horizontal layers sequentially (all CLI commands, then all Slack integration, then all agent runtime). But completing Phase 3 (full CLI) before Phase 5 (agent runtime) delivers no operator value — a complete CLI dispatching jobs to a dummy agent is less useful than a minimal CLI with a working agent.

**Decision**: Replace the phase structure with Sprints A-D. Each sprint pulls the minimum viable slice from multiple phases and delivers end-to-end functionality:

| Sprint | Vertical Slice |
|:-------|:---------------|
| A (Foundation) | AgentGroup rename + repo cleanup + minimal CLI + health |
| B (The Brain) | Agent process + ReAct loop + first tools + tool registry |
| C (The Experience) | Slack Bolt → API dispatch → agent execution → results in thread |
| D (Completeness) | Full CLI + memory + knowledge + interceptor + observability + watchdog |

**Rationale**: Sprint B (a working agent that thinks) is more compelling than complete Phase 3 (a full CLI dispatching to nothing). The sprint model optimizes for the fastest path to the "aha moment": operator asks a question → agent investigates → intelligent response appears.

---

## 24. Two-Layer WebSocket Architecture

**Problem**: The API has a WebSocket endpoint for agents (`/ws/agents/{agent_id}`) to receive jobs and send results. But users (admin UI, CLI) also need real-time streaming — seeing tokens as the agent reasons, watching the activity feed of all agents. Using the same WebSocket for both would conflate transport-level job dispatch with user-facing streaming.

**Decision**: Two separate WebSocket layers:

| Layer | Endpoint | Purpose | Consumers |
|:------|:---------|:--------|:----------|
| **Agent WebSocket** | `/ws/agents/{agent_id}` | Job dispatch, heartbeat, results, LLM usage | Agent processes |
| **Client WebSocket** | `/ws/sessions/{session_id}` | Streaming tokens for a chat session | Admin UI, future CLI |
| **Activity WebSocket** | `/ws/activity` | Real-time fleet-wide activity feed | Admin UI dashboard |
| **SSE fallback** | `/sessions/{session_id}/stream` | HTTP-compatible streaming for simpler clients | CLI, integrations |

The API bridges between these layers: agent sends `job_progress` → API pushes to all client WebSocket connections subscribed to that session.

**Rationale**: Agent WebSocket is a control-plane transport concern (authentication, heartbeat, job lifecycle). Client WebSocket is a UX concern (streaming tokens, activity visualization). Different security models, different connection lifecycles, different consumers. Keeping them separate prevents accidental exposure of control-plane internals to user-facing surfaces.

---

## 25. Admin UI as Sprint C Deliverable (React + TypeScript)

**Problem**: The admin UI was originally scheduled as Phase 9 — after all core functionality. But the admin UI is the emotional core of the product. Seeing agents work in real-time, like watching a team of SREs investigate issues, is the "wow" moment. Deferring it means the most compelling user experience is built last.

**Decision**: The admin UI is part of Sprint C ("The Experience"), built in parallel with Slack integration. Both surfaces consume the same streaming API (Decision 24). Technology: React + TypeScript.

**Key views**:
- **Console tabs**: Chat interface with tabbed sessions. Pick an agent group → start a session → chat. Streaming tokens displayed as the agent reasons.
- **Fleet dashboard**: All agents, status, current jobs, agent group health — real-time via activity WebSocket.
- **Activity feed**: Real-time feed of agent work. Tool calls, job progress, completions. This is what makes people feel like they have a team of SREs.
- **Job inspector**: Full reasoning chain — tool calls, intermediate results, final answer, token usage.

**Rationale**: The streaming API infrastructure needed for Slack (bridging `job_progress` to threads) is the same infrastructure the admin UI needs. Building them together avoids duplicate work and ensures the streaming API is designed for multiple consumers from the start. React + TypeScript is industry standard with the richest ecosystem for real-time WebSocket UIs.

---

## 26. Intentional Observability (Prometheus + OpenTelemetry)

**Problem**: The system needs observability for operators (fleet health, job throughput, cost tracking) and developers (tool performance, query latency, debugging). But auto-instrumented middleware floods dashboards with noise — every HTTP request, every SQLAlchemy query, every WebSocket frame. The signal drowns in noise.

**Decision**: Intentional metrics and traces only. Every metric and span is deliberately placed by a developer, not auto-generated. Implementation lives in `plumbing/telemetry.py`.

**Sprint A foundation**: Sprint A closes only the Prometheus/no-op metrics facade, `/metrics`, and intentional service-boundary metrics already implemented in the control plane. OpenTelemetry tracing remains deferred until the runtime and propagation points exist.

**Implementation**:
- **Prometheus metrics** — Counters, histograms, gauges defined in `plumbing/telemetry.py`. Exported at `/metrics`.
- **OpenTelemetry traces** — Deferred beyond Sprint A closeout. The long-term design is still service-boundary spans with propagated context, but the current foundation does not yet provide a tracer implementation.
- **Zero-cost when disabled** — Importing `plumbing/telemetry` when telemetry is disabled creates no-op stubs. No SDK initialization, no background threads, no network calls.

**Operator metrics** (what matters for running the fleet):

| Metric | Type | Source |
|:-------|:-----|:-------|
| `legion_agents_total` | Gauge (by status, group) | DispatchService |
| `legion_jobs_total` | Counter (by type, status, group) | DispatchService |
| `legion_job_duration_seconds` | Histogram (by type, group) | DispatchService |
| `legion_job_queue_depth` | Gauge (by group) | JobRepository |
| `legion_sessions_active` | Gauge (by group) | SessionService |
| `legion_llm_tokens_total` | Counter (by model, provider) | LLMUsageService |
| `legion_llm_cost_usd_total` | Counter (by model, group) | LLMUsageService |
| `legion_llm_latency_seconds` | Histogram (by model) | LLMUsageService |
| `legion_websocket_connections` | Gauge (agent vs client) | ConnectionManager |

**Developer metrics** (what matters for building and debugging):

| Metric | Type | Source |
|:-------|:-----|:-------|
| `legion_tool_calls_total` | Counter (by tool, agent) | Tool adapter |
| `legion_tool_duration_seconds` | Histogram (by tool) | Tool adapter |
| `legion_db_query_duration_seconds` | Histogram (by operation) | Repository methods |
| `legion_filter_evaluations_total` | Counter (by action) | FilterService |

**What we do NOT instrument**: Every HTTP request (uvicorn handles this), every WebSocket frame, framework internals, library-level noise.

**Rationale**: Observability should feel like a well-curated dashboard, not a firehose. Operators should open Grafana and immediately see fleet health, job throughput, and cost. Developers should see tool performance and query latency. Everything else is noise.

---

## 27. Plugin System with Core Tools as First Plugins

**Problem**: Tools need to be discoverable at runtime. The codebase already has three proto-plugin systems (CLI registry, Slack registry, tool adapter). External contributors should be able to add tools the same way core tools are added. If we design the tool registry right in Sprint B, it IS the plugin system.

**Decision**: Formalize the plugin system using Python entry points (`importlib.metadata`). Core tools are the first plugins. The `@tool` decorator in `plumbing/plugins.py` annotates metadata. Discovery via entry points in `pyproject.toml`.

**Sprint A foundation**: Sprint A closes only the metadata contract in `plumbing/plugins.py`. That contract carries tool classification (`category`, `read_only`) without adding runtime discovery or adapters yet.

**Architecture**:

```
plumbing/plugins.py              <- @tool decorator (metadata only, no AI imports)
  ↑ used by
core/kubernetes/__init__.py      <- @tool decorated functions
core/database/__init__.py        <- @tool decorated functions
core/network/__init__.py         <- @tool decorated functions
  ↑ discovered by
agents/tools.py                  <- entry point discovery → LangChain StructuredTool adapter
```

**The `@tool` decorator**:
```python
# plumbing/plugins.py
def tool(*, category: str, read_only: bool = True):
    """Annotate a core function as a tool. Metadata only — no AI framework imports."""
    def decorator(func):
        func._tool_meta = ToolMeta(
            name=func.__name__,
            category=category,
            read_only=read_only,
            description=func.__doc__,
        )
        return func
    return decorator
```

**Entry points** (in `pyproject.toml`):
```toml
[project.entry-points."legion.tools"]
kubernetes = "legion.core.kubernetes:tools"
database = "legion.core.database:tools"
network = "legion.core.network:tools"
```

**Third-party plugins** use the same mechanism:
```toml
# In a separate package: legion-datadog-tools
[project.entry-points."legion.tools"]
datadog = "legion_datadog:tools"
```

`pip install legion-datadog-tools` → tools immediately available to agents.

**What this enables now**: A stable metadata contract for core and third-party tools, so later discovery and adapter work can rely on a fixed shape.

**What this enables later**: Core tools discoverable via entry points. `legion-cli plugins list` shows all tools. The agent graph loads tools dynamically based on what's installed.

**What this does NOT require yet**: Sandboxing for untrusted plugins, hot reload, plugin marketplace. Core plugins run in-process and are trusted.

**Rationale**: The difference between "hardcoded tool list" and "plugin system" is just how tools are discovered. Entry points (`importlib.metadata`) is the Python standard, costs almost nothing to implement, and makes the system extensible from day 1 without any over-engineering.

---

## 28. Agent CLI Plugins — Delegated Autonomous Agents

**Problem**: Operators want to delegate specialized tasks (code fixes, test generation, runbook writing) to purpose-built AI agent CLIs (OpenCode, Aider, Claude Code). These agents are trusted by operators for specific tasks in specific environments. How should Legion integrate them?

**Decision**: Agent CLIs are tool plugins. They use the same `@tool` decorator and entry point mechanism as core tools. They are classified as `read_only=False` (write/mutate), which means the tool interceptor gates them with human approval.

**Architecture**:
```
Operator: "fix the broken deployment manifest"
  → Legion Agent (triages, identifies the issue)
    → @tool opencode_edit (delegated coding task)
      → OpenCode CLI subprocess in scoped workspace
      → Creates branch + PR
    ← structured result (PR URL, diff summary)
  ← posted to Slack thread / Admin UI
```

**Guardrails** (see [Threat Model](./threat-model.md) Section 5):
- Workspace isolation — coding agents operate in scoped directories
- PR-only output — all changes go through version control, never direct push
- Human approval — tool interceptor gates execution
- Hard timeout — subprocess killed after configurable limit (default 5 minutes)
- Full audit trail — command, input, output linked to job and session

**Trust model**: Operators choose which agent CLIs are installed on which agents. The control plane enforces which agent groups can use which tools. Credentials stay local. Everything is audited.

**Why this matters**: Legion becomes an agent orchestration platform, not just an SRE agent. Operators build trust relationships with specific AI tools and Legion gives them controlled, audited access across their infrastructure.

---

## 29. Alembic for Database Migrations

**Problem**: The codebase uses `create_all()` on startup to create tables. This works for fresh databases but cannot handle schema changes (column renames, type changes, new constraints) on existing data. The AgentGroup rename (Decision 5) requires renaming `cluster_group_id` columns across multiple tables — impossible with `create_all()` against an existing PostgreSQL database.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Keep `create_all()` | Zero setup, fast for dev | Cannot alter existing tables. Production schema changes require manual SQL or data loss. |
| Alembic migrations | Industry standard, autogenerate from ORM, reversible, version-controlled | Small setup cost. Tests still use `create_all()` for speed. |

**Decision**: Alembic for all persistent databases. `create_all()` retained only for test fixtures (`sqlite:///:memory:`).

**Implementation**:
- `alembic init` in repo root, `env.py` configured to use `plumbing.database.Base.metadata` and `plumbing.config.database.DatabaseConfig`
- Initial migration generated from current ORM schema (baseline)
- The AgentGroup rename becomes the second migration — proving the workflow immediately
- App startup calls `alembic upgrade head` instead of `create_all()` for file-backed and PostgreSQL databases
- ORM Row classes remain the source of truth — `alembic revision --autogenerate` diffs against them

**Rationale**: This is a 2-hour task that prevents a class of deployment failures. Every schema change after initial deployment requires migration support. Deferring this to "later" means the first production deployment with a schema change becomes an emergency.

---

## 30. API Key Authentication in Sprint A

**Problem**: The API has zero authentication. All endpoints are open. The threat model identifies agent impersonation (S1, High) and operator impersonation (S2, High) as significant threats, but auth was deferred to "Future Work (After Sprint D)." This means Sprints A-D — including Sprint C where Slack events trigger agent actions on production infrastructure — all run without any access control.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Defer auth to post-Sprint D | Less work now | API exposed for entire development lifecycle. Sprint C Slack→agent→production path has no gate. |
| Full RBAC in Sprint A | Complete solution | Over-engineered for current stage. Blocks Sprint A progress. |
| Simple API key in Sprint A, RBAC later | Minimal effort, prevents accidental exposure | Not per-user. Shared secret. |

**Decision**: Simple `X-API-Key` header middleware in Sprint A. RBAC deferred to post-Sprint D as planned.

**Implementation**:
- Middleware in `api/auth.py` checks `X-API-Key` header against `LEGION_API_KEY` env var
- Exempt paths: `/health`, `/health/ready` (monitoring), `/docs`, `/openapi.json` (development)
- WebSocket agent endpoint (`/ws/agents/`) uses the same key as a query parameter (WebSocket headers are limited)
- **When `LEGION_API_KEY` is not set, auth is disabled** — preserves `docker compose up` simplicity for local dev
- Returns 401 Unauthorized with clear error message when key is missing/wrong

**Rationale**: The cost of adding this is ~30 minutes. The cost of not having it is an open API that dispatches commands to production infrastructure. This isn't security theater — it's the minimum viable gate. RBAC adds per-user identity; this just answers "is the caller authorized at all?"

---

## 31. Per-Job Token Budget from Sprint B

**Problem**: The threat model identifies LLM cost explosion (D4) as High severity. The original plan defers token tracking to Sprint D (LLMUsageService). But Sprint B introduces the ReAct loop — and a runaway loop during development or testing can burn through significant API credits. A single misconfigured prompt or infinite tool-call cycle could cost hundreds of dollars before anyone notices.

**Decision**: `agents/context.py` enforces a per-job token ceiling from Sprint B. Default 32,768 tokens. Configurable via `AgentRunnerConfig.max_job_tokens`.

**Implementation**:
- Token counter in `agents/context.py` accumulates input + output tokens per job
- When budget exhausted: agent stops the ReAct loop, returns partial results with a `budget_exhausted` flag
- Not a hard kill — the agent completes the current LLM call, then stops gracefully
- Token count reported in `job_result` message for visibility
- Full LLM usage tracking (LLMUsageService, cost estimation, aggregation) remains in Sprint D — this is just the circuit breaker

**Rationale**: Cost control is a safety mechanism, not a feature. It belongs next to the code that spends money (the ReAct loop), not in a later sprint. The full telemetry system (Sprint D) provides dashboards and aggregation; this decision provides the circuit breaker that prevents a $500 surprise during a Tuesday afternoon test run.

---

## 32. Audit Log as First-Class Subsystem

**Problem**: Agent actions on production infrastructure need a complete, queryable, exportable record. The original plan tracks tool calls via Prometheus metrics and inter-agent queries as Jobs in the database, but these are scattered across different subsystems. There's no single place to answer "what did agent X do in the last hour?" For enterprise adoption, compliance, and incident forensics, auditing must be its own subsystem with structured events and pluggable outputs.

**Decision**: A dedicated `AuditService` with structured `AuditEvent` records, an in-process buffer, and pluggable sinks.

**Architecture**:
- `AuditService.emit(event)` is called by services, middleware, and agents at every meaningful action boundary
- Events buffered in-process, flushed asynchronously to configured sinks
- **Sinks** (pluggable, multiple can be active):
  - PostgreSQL `audit_events` table (default, queryable)
  - Structured JSONL file (zero-infrastructure, rotatable, ship-to-S3)
  - Webhook (POST to external endpoint — SIEM, Splunk, Elastic, Sentinel, Datadog Logs)
  - Redis Stream (high-throughput buffer for real-time consumers, when Redis is available)

**Event schema**: Every event has `id`, `timestamp`, `event_type`, `actor_type`, `actor_id`, `org_id`, `resource_type`, `resource_id`, `context` (dict), `outcome`. See [security-and-operations.md](./security-and-operations.md) Section 7.3 for the full schema and event catalog.

**Design constraints**:
- Audit writes MUST NOT block the hot path — buffer and async flush, drop with metric if buffer fills
- Events are immutable — append-only, no updates, no deletes
- Query API at `GET /audit/events` with cursor pagination and field filtering

**Rationale**: An audit log is not a nice-to-have for a system that executes commands on production infrastructure. It's the foundation for compliance, forensics, trust-building, and SIEM integration. Making it a first-class subsystem with its own sink architecture means it can grow from "PostgreSQL table" to "enterprise SIEM feed" without redesigning the plumbing.

---

## 33. Messaging Architecture and WebSocket Reliability

**Problem**: The control plane communicates with agents over persistent WebSocket connections. The plan describes the WebSocket protocol (Decision 9, Decision 24) and Redis for durability (Decision 17), but doesn't fully specify the message protocol, failure modes, delivery guarantees, or the single-worker constraint. These need to be explicit before Sprint B, because the agent process depends on them.

**Decision**: Define a complete message protocol, document all failure modes and recovery mechanisms, and explicitly constrain the system to single-worker until Redis backplane is implemented.

**Key decisions within this**:

1. **All WebSocket messages are JSON with a `type` field** for routing. Message types are enumerated and versioned.
2. **State-changing messages are idempotent by resource ID** (job_id, request_id). Duplicate delivery is safe — receivers check current state before applying.
3. **Delivery guarantees**: Job dispatch and results are at-least-once (DB is source of truth, heartbeat timeout triggers reassignment). Progress/streaming is best-effort (UX optimization, not a durability requirement).
4. **Single-worker constraint**: `ConnectionManager` is in-process. Multiple uvicorn workers WILL break job dispatch. Enforce `workers=1` in default config, log warning if misconfigured. This is acceptable for hundreds of agents.
5. **Redis migration path**: When scaling is needed, replace `ConnectionManager.send_job_to_agent()` with Redis publish. Service layer doesn't change. Only the notification path changes.

See [security-and-operations.md](./security-and-operations.md) Section 9 for the full connection lifecycle diagram, message type catalog, failure mode table, and Redis backplane architecture.

**Rationale**: WebSocket systems fail in subtle ways — split brain, duplicate delivery, silent disconnects, worker partitioning. Documenting the protocol and failure modes explicitly prevents the class of bugs where "it works on my laptop with one agent" but fails in production with 50 agents across 3 availability zones. The single-worker constraint is the most important: it prevents a week of debugging why "jobs sometimes don't dispatch."

---

## 34. Event as a Domain Model

**Problem**: The system currently treats input events implicitly — a Slack message payload gets stuffed directly into a `Job(payload=str)`. There is no structured representation of *what happened*. An alert from Prometheus Alertmanager, a PagerDuty incident, a Datadog monitor trigger, and a Slack message from a human are fundamentally different things, but they all become the same opaque string. This makes deduplication, routing, querying, and auditing of input events impossible at the domain level.

Additionally, Slack is currently the only input surface. For a product that people can demo, evaluate, and adopt incrementally, requiring Slack app setup (which is often tightly controlled by security teams) is a barrier. The system needs a standalone event ingestion path.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Keep events implicit (payload in Job) | No new concepts, simple | No dedup, no event history independent of jobs, no webhook ingestion, Slack-only |
| Event as a first-class domain model | Dedup, source-independent routing, queryable event stream, audit trail | New entity, new service, migration for existing flows |

**Decision**: `Event` is a domain model with a two-layer structure: **raw envelope** (always present) and **normalized fields** (best-effort, all nullable).

**Why two layers**: External alert sources do not share a schema. Prometheus Alertmanager sends `labels.severity` (user-defined, optional). Datadog sends `alert_type` (`error`, `warning`, `info`, `success`). CloudWatch sends `NewStateValue` (`ALARM`, `OK`, `INSUFFICIENT_DATA`). PagerDuty sends CEF `severity`. OpsGenie sends `priority` (`P1`–`P5`). Some sources have no severity concept at all. A domain model that requires `severity: str` would lie. A domain model that makes it nullable and best-effort is honest.

**The model**:

| Field | Type | Layer | Notes |
|:------|:-----|:------|:------|
| `id` | `str` | — | Primary key |
| `org_id` | `str` | — | FK → Organization |
| `source` | `str` | Raw | `alertmanager`, `datadog`, `cloudwatch`, `pagerduty`, `opsgenie`, `slack`, `api`, `generic` |
| `source_id` | `str \| None` | Raw | The source system's ID for this event (for correlation) |
| `raw_payload` | `dict` | Raw | Full JSON as received, untouched |
| `fingerprint` | `str \| None` | Normalized | Derived hash for dedup (source + key fields) |
| `severity` | `EventSeverity \| None` | Normalized | `critical`, `high`, `medium`, `low`, `info` — mapped by source adapter |
| `title` | `str \| None` | Normalized | Extracted summary |
| `service` | `str \| None` | Normalized | Affected service name |
| `status` | `EventStatus` | — | `RECEIVED`, `ROUTED`, `SUPPRESSED`, `DEDUPLICATED` |
| `agent_group_id` | `str \| None` | — | Set on routing — FK → AgentGroup |
| `job_id` | `str \| None` | — | Set when Event produces a Job — FK → Job |
| `created_at` | `datetime` | — | |

**Event → Job separation**: Events are the input stream (append-only, auditable). Jobs are the work stream. One event may produce zero jobs (suppressed by filter rules or deduplication) or one job. Multiple events with the same fingerprint within a dedup window map to zero additional jobs. The event stream answers "what alerts fired?" independently from "what work was done?"

**Slack stays first-class**: Slack alert channel messages become Events with `source="slack"`. The existing ChannelMapping + FilterService flow is preserved — it just now produces an Event first, then the Event produces a Job. Slack chat messages (CHAT mode channels) continue to bypass the event model and create Jobs directly through SessionService, because they're interactive conversations, not alert events.

See [domain-model.md](./domain-model.md) for the full entity definition and state machine.

---

## 35. Event Ingestion and Source Adapters

**Problem**: With Event as a domain model (Decision 34), the system needs a way to ingest events from external sources. The current architecture only accepts input through Slack. External monitoring tools (Alertmanager, Datadog, CloudWatch, PagerDuty, OpsGenie) need webhook endpoints. Custom integrations need a generic endpoint.

**Decision**: A source adapter pattern with per-source webhook endpoints and a generic fallback.

**Architecture**:

```
POST /events/ingest/alertmanager  → AlertmanagerAdapter → normalized Event
POST /events/ingest/datadog       → DatadogAdapter      → normalized Event
POST /events/ingest/cloudwatch    → CloudWatchAdapter    → normalized Event
POST /events/ingest/pagerduty     → PagerDutyAdapter     → normalized Event
POST /events/ingest/opsgenie      → OpsGenieAdapter      → normalized Event
POST /events/ingest/generic       → GenericAdapter       → Event (raw only)
Slack message (alert channel)     → SlackAdapter         → normalized Event
```

**Source adapters** are small, stateless functions:
```
adapter(raw_payload: dict, config: EventSourceConfig) → NormalizedFields
```

Each adapter knows how to extract `severity`, `title`, `service`, and compute a `fingerprint` from the source-specific payload. The generic adapter extracts nothing — everything stays in `raw_payload`, and routing falls back to filter rules against the raw content.

**EventSourceConfig** — per-source configuration stored in the database:

| Field | Type | Notes |
|:------|:-----|:------|
| `id` | `str` | Primary key |
| `org_id` | `str` | FK → Organization |
| `source` | `str` | Adapter name: `alertmanager`, `datadog`, `generic`, etc. |
| `agent_group_id` | `str` | Default routing target |
| `default_severity` | `EventSeverity \| None` | Fallback when source doesn't provide severity |
| `auth_token` | `str` | Webhook authentication token (per-source) |
| `field_mappings` | `dict \| None` | Custom field extraction for generic webhooks |
| `enabled` | `bool` | `true` |

**Routing flow**:
1. Webhook receives payload → adapter normalizes → Event created (status: RECEIVED)
2. **EventRouter** evaluates routing rules:
   - If `EventSourceConfig.agent_group_id` is set → route to that group
   - If severity-based rules exist → evaluate against normalized severity
   - If filter rules exist for the source → evaluate against raw_payload
   - No match → Event stays RECEIVED (no job created), queryable for review
3. If routed → DispatchService.create_job() → Event updated (status: ROUTED, job_id set)

**Deduplication**: Before routing, EventService checks for existing events with the same `fingerprint` within a configurable window (default 5 minutes). Duplicates are marked `DEDUPLICATED` and linked to the original event. No new job is created.

**Why per-source endpoints instead of one generic endpoint**: Source-specific endpoints allow:
- Type-safe payload validation per source
- Source-specific auth (Alertmanager uses basic auth, PagerDuty uses webhook signatures, Datadog uses API keys)
- Clear documentation per integration
- The generic endpoint exists for everything else

---

## 36. Slack-Optional Deployment

**Problem**: Slack is currently the only input surface beyond the CLI. Setting up a Slack app requires workspace admin access, is often controlled by security teams, and forces users to adopt Slack as their collaboration tool. For product adoption — demos, evaluations, proof-of-concepts — this is a significant barrier. Users should be able to run Legion, point a webhook at it, and see agents investigate alerts without any Slack configuration.

**Decision**: Slack is a first-class surface but not a required one. The system is fully functional without Slack for event ingestion, agent management, and operator interaction.

**What works without Slack**:
- Event ingestion via webhooks (`POST /events/ingest/{source}`)
- Fleet management via CLI and API
- Interactive sessions via API and Admin UI (`POST /sessions`, `/sessions/{id}/messages`)
- Agent dispatch, execution, and results
- Real-time streaming via Admin UI WebSocket
- Full audit trail

**What requires Slack**:
- Alert channel monitoring (ChannelMapping + FilterService flow)
- Chat channel sessions with thread-based agent affinity
- Slack-native result posting and approval flows
- `@legion` mentions

**Deployment modes updated**:

| Mode | Slack | Event Ingestion | Use Case |
|:-----|:------|:----------------|:---------|
| **Demo** | No | Webhooks + CLI + Admin UI | Try the product, PoC, evaluation |
| **Simple** | Yes | Slack only | Single-node Slack bot, no fleet |
| **Fleet** | Optional | Webhooks + Slack + CLI + Admin UI | Full distributed fleet |

**Why this matters for adoption**: A user should be able to `docker compose up`, configure a webhook in their monitoring tool, and watch an agent investigate an alert — all within 15 minutes, without asking their security team for Slack app permissions. Slack integration is the upgrade path, not the prerequisite.

The existing `legion-slack` standalone mode continues unchanged. The new `legion-api` mode works with or without Slack Bolt mounted.

---

## 37. Event Immutability and FK Direction

**Problem**: Decision 34 defines Event with a `job_id` field that gets written back after routing creates a Job. This violates the "events are immutable" principle — creating the Event, creating the Job, then updating the Event with `job_id` is a write-back pattern that makes events mutable. Additionally, the Event model lacks a `type` field to distinguish alert triggers from webhooks, schedules, or manual requests. And there's no `correlation_key` to group related events (e.g., multiple alerts about the same service outage).

**Decision**: Three changes to the Event model:

1. **Move the FK**: `job.event_id` (nullable) instead of `event.job_id`. A Job knows why it exists. Not every Job comes from an Event (chat sessions, manual CLI dispatch), so `event_id` is nullable. Event stays truly immutable — no write-back after creation.

2. **Add `type` enum**: `EventType`: `ALERT`, `WEBHOOK`, `SCHEDULE`, `MANUAL`. The `source` field tells you *who* sent it (alertmanager, datadog, slack); `type` tells you *what kind* of trigger it is. This enables type-specific behavior: alerts may preempt scheduled work, you dedup alerts but not manual requests, reporting distinguishes "how many alerts vs manual investigations this week?"

3. **Add `correlation_key`**: Nullable string on Event. Source adapters populate it from source-specific fields (e.g., Alertmanager `alertname + labels.service`, Datadog `monitor_id`). Used for dedup now, incident grouping later (Decision 39).

**Impact**: `dedup_ref_id` stays on Event (self-reference for dedup chains is still useful). `status` and `agent_group_id` stay on Event as write-once fields (set during routing, never changed again — not truly mutable, more like "finalized on creation").

---

## 38. Chat Sessions Are Not Events

**Problem**: Should chat messages (operator typing in Slack, Admin UI, or CLI) create Events? A uniform pipeline (everything is an Event) simplifies the model, but chat messages are fundamentally different from alert triggers.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Chat creates Events (type=`chat`) | Uniform pipeline, single audit path | Extra hop adds latency to interactive chat. Dedup makes no sense for chat. "What pods are crashlooping?" isn't an "event." Semantic confusion. |
| Chat is a separate flow | Direct dispatch, fast interactive feel. Clean semantics — sessions are conversations, events are triggers. | Need separate audit mechanism for chat. |

**Decision**: Chat stays a separate flow. Sessions create Jobs directly through SessionService → DispatchService. No Event intermediary.

**Audit parity**: The AuditEvent model (Decision 42) provides uniform audit coverage. Every Job — whether triggered by an Event or a Session — emits AuditEvents for tool calls, decisions, and results. The audit trail is on Job execution, not on the trigger mechanism.

**Session policy**: Execution mode (Decision 41) applies to AgentGroup, which governs both event-triggered and session-triggered jobs. Chat sessions inherit the group's policy. Same guardrails, different entry path.

---

## 39. Incident as a Grouping Entity

**Problem**: When Alertmanager fires 5 alerts about the same service outage, the current design creates 5 Events → 5 Jobs → 5 agents working independently. Dedup (fingerprint within time window) catches exact duplicates, but related-but-different alerts (pod crashlooping + service 5xx + database connection timeout) are treated as independent. There's no way to group related work or track incident lifecycle across multiple events and jobs.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| No Incident model (current) | Simpler, fewer entities, faster to build | No grouping, duplicate investigation, no incident lifecycle |
| Incident as grouping entity | Groups related Events and Jobs, prevents duplicate work, enables lifecycle tracking (open→investigating→resolved) | More complexity, correlation logic is non-trivial |

**Decision**: Incident is a domain entity that groups related Events and Jobs. **Design now, build in Sprint D.**

**Model** (Sprint D):

| Field | Type | Notes |
|:------|:-----|:------|
| `id` | `str` | Primary key |
| `org_id` | `str` | FK → Organization |
| `title` | `str` | Human-readable summary |
| `status` | `IncidentStatus` | `OPEN`, `INVESTIGATING`, `MITIGATED`, `RESOLVED` |
| `severity` | `EventSeverity` | Highest severity from associated events |
| `correlation_key` | `str \| None` | Groups events by shared correlation |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |

**Relationships**: `Job.incident_id` (already exists) links jobs to incidents. `Event.correlation_key` is the bridge — events with the same correlation key within a time window get associated to the same incident. The correlation logic lives in a future `IncidentService`.

**Why Sprint D, not Sprint C**: Sprint C builds the Event model and ingestion pipeline. By Sprint D, there's real event data and usage patterns to inform correlation logic. Building Incident without real events would be speculative.

**What to build now**: `correlation_key` on Event (Decision 37). This is the foundation — cheap to add, preserves the option, source adapters populate it.

**Integration with existing Incident model**: The existing `domain/incident.py` Incident model (used by the incident bot) becomes the fleet Incident model. Same entity, enhanced with correlation_key and event associations. The existing `IncidentService` gains event-aware methods in Sprint D.

---

## 40. Capability-Based Intra-Group Dispatch

**Problem**: The current design routes jobs to an AgentGroup, then picks any idle agent. But agents within a group may have different capabilities — one has `kubectl` access, another has `psql`, a third has both. Dispatching a database investigation to an agent without `psql` wastes a job cycle.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| AgentGroup-only routing (current) | Simple FK lookup, operator-controlled | Wrong agent gets wrong job, no capability awareness |
| Capability-only routing | Fully dynamic, auto-scaling friendly | Complex matching algorithm, removes operator control |
| AgentGroup + capabilities (layered) | Operator controls group assignment, capabilities refine within group | Slightly more complex dispatch query |

**Decision**: Both, layered. AgentGroup is the primary routing unit (explicit, operator-controlled). Capabilities are metadata on Agent used for **intra-group matching** by DispatchService.

**Changes**:
- `Agent.capabilities` (already exists as `list[str]`) — reported by agent at connect time. Values like `kubernetes`, `postgresql`, `datadog`, `ssh`.
- `Job.required_capabilities` (new, `list[str]`, default `[]`) — set by the caller or inferred from event source. Empty means "any agent in the group."
- `DispatchService.dispatch_pending()` — when matching pending jobs to idle agents within a group, prefer agents whose `capabilities` superset includes the job's `required_capabilities`. If no capable agent is idle, the job waits (not dispatched to an incapable agent).

**Examples**:
- Event from Alertmanager (k8s alerts) → Job with `required_capabilities: ["kubernetes"]` → dispatched to agent with kubectl
- Event from Datadog → Job with `required_capabilities: ["datadog"]` → dispatched to agent with Datadog API access
- Chat session query "what's the replication lag?" → Job with `required_capabilities: ["postgresql"]` → dispatched to agent with psql
- Generic triage → Job with `required_capabilities: []` → any idle agent

**Sprint**: Capability field on Agent already exists. `required_capabilities` on Job is a Sprint A addition (schema). Capability-aware dispatch logic is Sprint B (DispatchService enhancement).

---

## 41. Policy Model and Execution Modes

**Problem**: The current design has `read_only` on the `@tool` decorator and a tool interceptor planned for Sprint D, but no formal policy model. There's no way to express "agents in the prod group require approval for destructive actions" vs "agents in the dev group can auto-execute." No SRE team will deploy agents that can `kubectl delete pod` or `DROP TABLE` without policy gates.

**Decision**: A Policy model with execution modes, scoped to organization or agent group. **Design now, build in Sprint D** alongside the tool interceptor.

**Execution modes** (trust levels, applied per AgentGroup):

| Mode | Behavior | Use Case |
|:-----|:---------|:---------|
| `READ_ONLY` | Agent can only call `read_only=True` tools. Write tools are blocked. | Monitoring-only, zero-trust environments |
| `PROPOSE` | Agent proposes write actions, never executes them. Results include "would have run: ..." | Evaluation, building trust |
| `REQUIRE_APPROVAL` | Write tools pause for human approval (Slack button, Admin UI confirm, CLI prompt). Timeout → deny. | Production with human oversight |
| `AUTO_EXECUTE` | Agent executes all tools autonomously. Full trust. | Dev environments, trusted automation |

**AgentGroup gains**: `execution_mode` field (enum, default `READ_ONLY`). This is the group-wide default.

**Policy entity** (Sprint D):

| Field | Type | Notes |
|:------|:-----|:------|
| `id` | `str` | Primary key |
| `org_id` | `str` | FK → Organization |
| `scope` | `PolicyScope` | `ORG`, `GROUP`, `CAPABILITY` |
| `scope_id` | `str \| None` | AgentGroup ID or capability name (null for org-wide) |
| `rules` | `list[PolicyRule]` | Action-specific overrides |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |

**PolicyRule**: `{ action: str, requires_approval: bool, allowed: bool }` — e.g., `{ action: "restart_pod", requires_approval: true }`, `{ action: "read_logs", requires_approval: false }`.

**Evaluation order**: Tool-specific rule → Group policy → Org policy → `execution_mode` default. Most specific wins.

**Why design now**: The `execution_mode` field on AgentGroup is cheap to add in Sprint A. The tool interceptor (Sprint D) uses it. The full Policy entity comes in Sprint D when the approval workflow (Slack buttons, Admin UI confirm) is built. Designing the model now ensures the interceptor is built against a clear contract.

---

## 42. Granular Audit Trail (AuditEvent Per Tool Call)

**Problem**: Decision 32 defines an audit log subsystem with pluggable sinks, but the event schema is coarse — it tracks service-level actions (job created, session opened, agent connected), not agent-level actions (tool calls, decisions, results). An SRE team needs to know: "The agent ran `kubectl delete pod payments-xyz` at 14:32:07 because it determined the pod was in CrashLoopBackOff." The current design can't answer that question.

**Decision**: Extend the audit subsystem with a granular `AuditEvent` model that records every tool call, decision, and result during job execution.

**AuditEvent entity**:

| Field | Type | Notes |
|:------|:-----|:------|
| `id` | `str` | Primary key |
| `job_id` | `str` | FK → Job |
| `agent_id` | `str` | FK → Agent |
| `session_id` | `str` | FK → Session (denormalized for query efficiency) |
| `org_id` | `str` | FK → Organization (denormalized) |
| `action` | `AuditAction` | `TOOL_CALL`, `TOOL_RESULT`, `LLM_DECISION`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`, `APPROVAL_DENIED` |
| `tool_name` | `str \| None` | Tool that was called (null for LLM decisions) |
| `input` | `dict \| None` | Tool input parameters or LLM prompt summary |
| `output` | `dict \| None` | Tool output or LLM response summary |
| `duration_ms` | `int \| None` | Execution time |
| `created_at` | `datetime` | |

**Relationship to Decision 32**: AuditEvent is a specialized, high-volume event type within the audit subsystem. It flows through the same sink architecture (PostgreSQL, JSONL, webhook, Redis Stream). The existing `AuditService.emit()` interface handles both service-level audit events and granular tool-call AuditEvents.

**What this enables**:
- Full reasoning chain replay: "Show me everything agent-1 did on job X"
- Policy enforcement evidence: "Agent requested approval for `kubectl delete pod`, operator denied at 14:33"
- Cost attribution: tool call durations tied to specific jobs and sessions
- Compliance: complete record of every action taken on production infrastructure

**Sprint**: AuditEvent entity design is Sprint B (when the agent process and tool calls are built). Full sink integration is Sprint D (alongside LLMUsageService and the tool interceptor).

---

## 43. Job Lifecycle Expansion

**Problem**: The current Job model has two types (`TRIAGE`, `QUERY`) and a linear lifecycle (`PENDING → DISPATCHED → RUNNING → COMPLETED/FAILED/CANCELLED`). This is insufficient for the range of work agents will perform and doesn't support closed-loop validation (did the remediation actually fix the problem?).

**Decision**: Expand job types and add an optional VERIFYING state.

**Job types** (phased rollout):

| Type | Description | Sprint |
|:-----|:------------|:-------|
| `TRIAGE` | Investigate an alert or event, determine severity and impact | A (existing) |
| `QUERY` | Answer an operator's question using available tools | A (existing) |
| `INVESTIGATE` | Deep-dive analysis — root cause, blast radius, dependencies | B |
| `DIAGNOSE` | Focused diagnostic — check specific subsystem health | B |
| `SUMMARIZE` | Generate summary of incident, job results, or time range | C |
| `REMEDIATE` | Take corrective action (restart pod, scale deployment, failover) | D |
| `VALIDATE` | Verify that a remediation was effective | D |

**VERIFYING state** (optional):

```
                dispatch_to(agent_id)         start()
PENDING ─────────────────────→ DISPATCHED ──────→ RUNNING
  │                               │                  │
  │ cancel()                      │ cancel()         ├── complete(result)
  ↓                               ↓                  │        ↓
CANCELLED                    CANCELLED           │   COMPLETED
                                                     │
                                                     ├── verify()
                                                     │        ↓
                                                     │   VERIFYING ──→ COMPLETED
                                                     │        │
                                                     │        ↓
                                                     │     FAILED
                                                     │
                                                     └── fail(error)
                                                              ↓
                                                           FAILED
```

**RUNNING → VERIFYING** is optional. Investigation and query jobs go directly to COMPLETED. Remediation jobs (Sprint D) transition to VERIFYING to confirm the fix worked: "I restarted the pod — let me check if it's healthy now." VERIFYING → COMPLETED on success, VERIFYING → FAILED if validation fails.

**Why expand types now**: Job type determines the system prompt, tool subset, and expected output format. Defining the taxonomy early (even if only TRIAGE and QUERY are implemented in Sprint A) ensures the enum is extensible without migration headaches. New types are additive — no existing code changes when INVESTIGATE is added in Sprint B.

---

## 44. Message Entity for Structured Session Timelines

**Problem**: Sessions group Jobs and track agent affinity, but there's no structured record of the conversation itself — human questions, agent findings, tool summaries, approval requests, status updates. Without a Message entity, the session timeline is reconstructed by joining Jobs and AuditEvents, which loses the conversational thread, human-provided context, and structured findings that make sessions a live working environment rather than a job tracker.

The two core features that define Legion's value depend on this:
1. **Interactive Agent Interrogation** — user asks questions, agent investigates, user provides context, agent adapts strategy, all within a persistent session with a live timeline.
2. **Incident + Interactive Session** — event triggers investigation, agent streams findings, user joins session, collaborates with agent in real-time, approves actions, full timeline preserved.

Both require a structured timeline that captures not just what the agent did (AuditEvent), but the full conversation: human input, agent observations, proposed actions, approval flows, and system events.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Reconstruct timeline from Jobs + AuditEvents | No new entity | Lossy — human messages aren't AuditEvents. No structured message types. No conversational thread. |
| Message entity on Session | Full structured timeline, typed messages, human + agent + system authors, rich metadata | New entity, new repository, more writes per session |

**Decision**: `Message` is a domain entity on `Session`. Every significant interaction within a session — human question, agent finding, tool execution summary, approval request, status change — is a Message.

**Message entity**:

| Field | Type | Notes |
|:------|:-----|:------|
| `id` | `str` | Primary key |
| `session_id` | `str` | FK → Session |
| `job_id` | `str \| None` | FK → Job (null for human messages, system events without a job) |
| `author_type` | `AuthorType` | Who created this message |
| `author_id` | `str` | User identity (for HUMAN), agent_id (for AGENT), `"system"` (for SYSTEM) |
| `message_type` | `MessageType` | Structured type for rendering and filtering |
| `content` | `str` | Primary text content |
| `metadata` | `dict` | Structured payloads — tool output, approval details, scope info, etc. |
| `created_at` | `datetime` | |

**Enums**:
- `AuthorType`: `HUMAN`, `AGENT`, `SYSTEM`
- `MessageType`: `HUMAN_MESSAGE`, `AGENT_FINDING`, `AGENT_PROPOSAL`, `TOOL_SUMMARY`, `APPROVAL_REQUEST`, `APPROVAL_RESPONSE`, `SYSTEM_EVENT`, `STATUS_UPDATE`

**Message types explained**:

| Type | Author | When |
|:-----|:-------|:-----|
| `HUMAN_MESSAGE` | HUMAN | User asks a question, provides context, gives instructions |
| `AGENT_FINDING` | AGENT | Agent reports an observation or investigation result |
| `AGENT_PROPOSAL` | AGENT | Agent proposes an action that requires approval |
| `TOOL_SUMMARY` | AGENT | Summary of what tool was executed and key output |
| `APPROVAL_REQUEST` | SYSTEM | Formal approval request with action details |
| `APPROVAL_RESPONSE` | HUMAN | User approves or denies a proposed action |
| `SYSTEM_EVENT` | SYSTEM | Alert received, job created, agent assigned, state change |
| `STATUS_UPDATE` | SYSTEM | Incident or session state transitions |

**Relationship to AuditEvent**: Messages are the user-facing timeline — what you see in the UI. AuditEvents are the compliance-facing record — every tool call with input/output/duration. A single `TOOL_SUMMARY` message may correspond to multiple AuditEvents (the agent ran 3 kubectl commands, the message summarizes the findings). Messages are for collaboration; AuditEvents are for audit.

**Relationship to Job**: Messages reference the Job they relate to via `job_id`. A human message that triggers a new job gets `job_id` set after the job is created. Agent findings and tool summaries reference the job that produced them. Human messages providing context (not triggering new work) have `job_id = None`.

**Sprint**: Message schema and `MessageRepository` in Sprint A. Services populate messages during job execution in Sprint B. Legion UI renders the timeline in Sprint C.

**Why this is the missing piece**: Without Message, sessions are invisible containers. With Message, sessions become the live, auditable, execution-backed conversation layer that turns infrastructure into something you can interrogate.

---

## 45. Legion UI as Primary Surface

**Problem**: The Admin UI (Decision 25) was designed as a fleet management dashboard and chat interface — important but secondary to Slack. The Interactive Agent Interrogation and Incident Session flows (Decision 44) reveal that the session workspace is the core product experience: a live, persistent environment where humans and agents collaborate with real execution capabilities. This experience cannot be fully delivered through Slack (limited formatting, no structured timeline views, no job inspector, no approval workflows beyond buttons). The built-in UI should be the primary surface, not an admin afterthought.

**Options**:
| Option | Pros | Cons |
|:-------|:-----|:-----|
| Keep Admin UI as secondary dashboard | Less UI investment | Core experience limited to Slack constraints |
| Elevate to Legion UI as primary surface | Full control over UX, structured timelines, rich interaction | More frontend investment, but the same streaming API serves all surfaces |

**Decision**: Rename "Admin UI" to **"Legion UI"** and elevate it to the primary interaction surface. Slack and CLI remain first-class surfaces, but the Legion UI is where the full experience lives.

**What this changes from Decision 25**:

| Aspect | Admin UI (Decision 25) | Legion UI (Decision 45) |
|:-------|:----------------------|:-----------------------|
| **Role** | Fleet dashboard + chat | Primary investigation workspace |
| **Session view** | Console tabs for chat | Full session workspace: structured timeline, message types, live updates, job inspector, scope display |
| **Incident view** | Not specified | Incident workspace: bound session, event correlation, live investigation, approval workflows |
| **Message display** | Chat-style text | Structured by MessageType — findings, proposals, tool summaries, approvals are visually distinct |
| **Human input** | Text chat | Questions, context provision, action approval/denial, scope selection |
| **Job visibility** | Job inspector (click-through) | Inline — jobs are visible in the session timeline as they execute |
| **Agent status** | Fleet dashboard | Fleet dashboard + per-session agent status |

**Key views** (expanded from Decision 25):

1. **Session Workspace** — The core view. Structured timeline with typed messages. Scope display (cluster, service, agent group). Live streaming as agent works. Inline job status. Approval buttons for proposed actions. Human input for questions and context.
2. **Incident Workspace** — Session workspace bound to an incident. Shows correlated events, severity, status. Multiple jobs visible. Full investigation + remediation flow in one place.
3. **Fleet Dashboard** — Agent status, group health, active jobs. Real-time via activity WebSocket. (Same as Decision 25.)
4. **Event Stream** — Incoming events by source, status, severity. Click-through to session/job. (Same as Decision 25.)
5. **Activity Feed** — Real-time agent work across the fleet. (Same as Decision 25.)
6. **Job Inspector** — Full reasoning chain, tool calls, AuditEvent trail, token usage. Accessible from session timeline or standalone. (Enhanced from Decision 25.)

**Architecture impact**: No backend changes — the Legion UI consumes the same streaming API (WebSocket, SSE, REST) designed in Decisions 24 and 25. The Message entity (Decision 44) provides the structured data the UI renders. The elevation is a frontend design and priority change, not an infrastructure change.

**Why this matters**: Legion's value proposition is "a live, auditable, execution-backed conversation layer over real systems." That experience is:
- **Not just chat** — it's structured investigation with typed messages, tool execution, and approval workflows
- **Not a dashboard** — it's a workspace where the work happens inside the session
- **Not Slack-dependent** — the full experience works without Slack

The Legion UI is what makes users stop thinking "open Datadog, run kubectl, check logs" and start thinking "open the session and work with Legion."

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial consolidated version from decisions.md, 2026-03-20-planning.md, domains-and-apis__notes.md. Added decisions 4, 5, 16, 17, 18, 20 from planning notes. |
| 2026-03-29 | Added decisions 21 (drop InMemory repos), 22 (tool registry + adapter), 23 (vertical sprints). |
| 2026-03-29 | Added decisions 24 (two-layer WebSocket), 25 (admin UI in Sprint C with React + TypeScript). |
| 2026-03-29 | Added decisions 26 (intentional observability), 27 (plugin system with core tools as first plugins). |
| 2026-03-29 | Added decision 28 (agent CLI plugins). Threat model created as separate document. |
| 2026-03-29 | Architecture review: Added decisions 29 (Alembic migrations), 30 (API key auth in Sprint A), 31 (per-job token budget in Sprint B). |
| 2026-03-29 | Architecture review: Added decisions 32 (audit log as first-class subsystem), 33 (messaging architecture and WebSocket reliability). |
| 2026-03-29 | Event architecture: Added decisions 34 (Event as domain model), 35 (event ingestion and source adapters), 36 (Slack-optional deployment). |
| 2026-03-29 | Domain model refinement: Added decisions 37 (Event immutability + FK direction), 38 (chat is not an Event), 39 (Incident as grouping entity), 40 (capability-based dispatch), 41 (Policy model + execution modes), 42 (granular AuditEvent per tool call), 43 (job lifecycle expansion). |
| 2026-03-29 | Session and UI elevation: Added decisions 44 (Message entity for structured session timelines), 45 (Legion UI as primary surface). Message entity captures structured conversation timeline — human questions, agent findings, tool summaries, approval flows. Admin UI renamed to Legion UI and elevated to primary interaction surface. |
