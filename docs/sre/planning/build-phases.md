# Build Sprints

> Vertical delivery sprints. Each sprint delivers end-to-end functionality — from configuration to execution to output. The existing incident bot keeps working throughout.
>
> **Principle**: Design before build. Each sprint must be architecturally resolved (see [Decisions](./decisions.md)) before coding begins.

---

## Sprint Overview

| Sprint | What You Get | How You Test | Dependencies |
|:-------|:-------------|:-------------|:-------------|
| A | Fleet setup from terminal, clean codebase, observability, Alembic migrations, API key auth | `pytest`, `legion-cli fleet ...`, `/metrics`, `curl -H "X-API-Key: ..."` | Phases 1-2 (done) |
| B1 | Agent process skeleton — full job dispatch lifecycle without LLM | Agent process + API + mock executor | Sprint A |
| B2 | An agent that thinks — LLM-powered investigation, plugin system | Agent process + API + real cluster | Sprint B1 |
| C | Event ingestion (webhooks + Slack), streaming API, Legion UI. Usable without Slack. | Webhook → event → agent → result (no Slack needed). Or: Slack + browser + agent. | Sprint B2 |
| D | Production-ready: memory, knowledge, guardrails, policy engine, incident correlation, remediation, additional adapters | End-to-end integration | Sprint B2 |

**Pre-requisite**: Phases 1 (Domain + Services) and 2 (API + WebSocket) are complete. All fleet business logic, CRUD routes, and WebSocket agent connections exist.

---

## Sprint A: Setup Foundation

**Goal**: Clean up codebase, give operators a CLI for fleet configuration, establish observability primitives, and close foundational infrastructure gaps (migrations, authentication).

**Testable with**: `uv run pytest`, `legion-cli fleet ...`, `curl /metrics`, `curl -H "X-API-Key: ..." /orgs`

### Current Status

Sprint A is partially implemented. The repo already has the `AgentGroup` rename, `execution_mode`, fleet CRUD CLI foundation, health endpoints, API key middleware, `/metrics`, and initial telemetry/plugin scaffolding. The remaining work is now batched into local feature briefs so it can be parallelized safely with worktrees and delegated agents:

1. `Phase 1 job and message foundation`
2. `Phase 1 Alembic adoption`
3. `Phase 1 observability and plugin closeout`

Execution order:

1. Finish `Phase 1 job and message foundation` first because it still locks Sprint A schema direction.
2. Run `Phase 1 observability and plugin closeout` in parallel where it does not depend on migration timing.
3. Start `Phase 1 Alembic adoption` only after the remaining schema changes are settled enough to define the initial migration path.

### Work Items

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ A: AgentGroup Rename     │  │ B: Repository Cleanup    │  │ C: Minimal CLI           │
│                          │  │ (parallel with A)        │  │ (after A)                │
│ • ClusterGroup →         │  │ • Drop InMemory impls    │  │ • cli/fleet_client.py    │
│   AgentGroup in domain/  │  │ • Tests use sqlite://    │  │ • org create/list        │
│ • Update services/,      │  │   :memory:               │  │ • agent-group create/    │
│   api/, tests             │  │ • Remove contract test   │  │   list/token             │
│ • Update planning docs   │  │   parameterization       │  │ • agent list/status      │
│                          │  │                          │  │ • Rich table views       │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ D: Health Endpoints      │  │ E: Observability         │  │ F: Alembic Setup         │
│ (parallel with B)        │  │ (parallel with B)        │  │ (parallel with B)        │
│                          │  │                          │  │                          │
│ • /health, /health/ready │  │ • plumbing/telemetry.py  │  │ • alembic init + config  │
│                          │  │   (metrics + traces)     │  │ • Initial migration from │
│                          │  │ • plumbing/plugins.py    │  │   current schema         │
│                          │  │   (@tool decorator)      │  │ • Replace create_all()   │
│                          │  │ • /metrics endpoint      │  │   startup with           │
│                          │  │ • Instrument services    │  │   alembic upgrade head   │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐
│ G: API Key Auth          │  │ H: Tests                 │
│ (parallel with B)        │  │ (as items complete)      │
│                          │  │                          │
│ • X-API-Key middleware   │  │ • CLI integration tests  │
│ • Env: LEGION_API_KEY    │  │ • Updated repo tests     │
│ • Skip /health, /ws     │  │ • Dep direction test     │
│ • Optional in dev (not   │  │ • Telemetry unit tests   │
│   set = auth disabled)   │  │ • Auth middleware tests  │
└─────────────────────────┘  └─────────────────────────┘
```

### Deliverables

1. **AgentGroup rename**: `ClusterGroup` → `AgentGroup` across all domain models, repositories, services, API routes, schemas, and tests. AgentGroup gains `execution_mode` field (Decision 41, default `READ_ONLY`).
2. **Repository simplification**: Drop all `InMemory*Repository` classes. One SQLAlchemy implementation per ABC. Tests use `sqlite:///:memory:`.
3. **Minimal CLI**: `legion-cli fleet` subcommands for org, agent-group, and agent management. Thin HTTP client over the API.
4. **Health endpoints**: `/health` (liveness), `/health/ready` (readiness — DB reachable).
5. **Job schema additions**: `event_id` (nullable FK → Event, Decision 37), `required_capabilities` (list[str], Decision 40), expanded `JobType` enum (TRIAGE, QUERY initially — extensible), `VERIFYING` state added to `JobStatus` (Decision 43).
6. **Message schema** (Decision 44): `domain/message.py` with `AuthorType` and `MessageType` enums. `MessageRepository` with `save`, `list_by_session`, `list_by_job`. `messages` ORM table. This is the structured session timeline — human questions, agent findings, tool summaries, approval flows.
7. **Observability primitives** (Decision 26):
   - `plumbing/telemetry.py` — Prometheus metrics (counters, histograms, gauges) + OpenTelemetry tracer. No-ops when disabled. Zero cost to import.
   - `plumbing/plugins.py` — `@tool` decorator for core functions (metadata only, no AI framework imports). Entry point discovery via `importlib.metadata`. Foundation for the plugin system (Decision 27).
   - `/metrics` endpoint — Prometheus scrape target on the API.
   - Instrument `DispatchService`, `SessionService`, `FilterService` with intentional metrics (not auto-instrumented noise).
8. **Alembic database migrations** (Decision 29): Initialize Alembic, generate initial migration from existing ORM schema, wire into app startup. Replace `create_all()` with `alembic upgrade head`. The AgentGroup rename in item 1 becomes the second migration — proving the migration workflow from day one.
9. **API key authentication** (Decision 30): Simple `X-API-Key` header middleware on all routes except `/health`, `/health/ready`, and `/ws/agents/`. Configured via `LEGION_API_KEY` env var. When not set, auth is disabled (dev mode). When set, all requests must include the header. This is not RBAC — it's a shared secret gate to prevent accidental exposure. RBAC comes later.
10. **Tests**: Updated repository tests, CLI integration tests, dependency direction enforcement, telemetry unit tests, auth middleware tests, message repository tests.

### Remaining Work Breakdown

- **Already landed or mostly landed**
  - AgentGroup rename and `execution_mode`
  - SQLAlchemy-first repository direction with SQLite-backed tests
  - `legion-cli fleet` CRUD foundation and agent status views
  - `/health`, `/health/ready`, `/metrics`
  - `X-API-Key` middleware
  - `plumbing/telemetry.py` and `plumbing/plugins.py` scaffolding
- **Still pending**
  - Job schema additions (`event_id`, `required_capabilities`, extensible lifecycle/types)
  - Message timeline foundation (`domain/message.py`, repository, persistence)
  - Alembic setup and startup migration wiring
  - Observability/plugin closeout work to match the planning docs
- **Handoff mechanism**
  - Use `uv run legion-dev feature show "<title>"` to inspect a local brief.
  - Use `uv run legion-dev feature handoff "<title>"` to emit the deterministic prompt for a worktree, sub-agent, or external coding agent.

### What to Watch For

- The rename touches many files — do it first before other work branches off
- CLI is a thin API client — no business logic, no direct DB access (Decision 8)
- Registration token for agent groups — the CLI `agent-group token` command generates/displays a token agents use to self-register
- Telemetry must be zero-cost when disabled — no SDK initialization, no background threads. `plumbing/telemetry.py` is importable from any layer without side effects.
- The `@tool` decorator in `plumbing/plugins.py` annotates metadata only — it does NOT import LangChain or any AI framework
- **Alembic**: Use `--autogenerate` for the initial migration. Keep `create_all()` available for test fixtures (`sqlite:///:memory:` doesn't need migrations). Production and dev-with-file-DB use Alembic.
- **Single-worker constraint**: Until Redis backplane is implemented (Decision 17), the API MUST run as a single uvicorn worker. `ConnectionManager` is in-process only — multiple workers would partition WebSocket connections and break job dispatch. Document this in deployment notes and enforce via default config (`workers=1`).
- **Auth in tests**: Test fixtures should pass the API key header or use a test app with auth disabled. Don't let auth make the test suite painful.

---

## Sprint B: The Brain

**Goal**: An agent process that connects to the API, receives jobs, investigates infrastructure using LLM + tools, and returns intelligent results. Core tools are the first plugins.

**Testable with**: Run `legion-agent` locally, point at API, dispatch a job, see it investigate your cluster. `legion-cli plugins list` shows discovered tools.

> **Note**: Sprint B is the highest-risk sprint. It integrates the WebSocket job loop, LangGraph runtime, tool plugin system, and real infrastructure tools for the first time. To reduce risk, it is split into two milestones with an intermediate validation point.

### Milestone B1: The Skeleton (agent process without LLM)

**Goal**: A real agent process that connects, receives jobs, executes a hardcoded response, and returns results. Validates the full job dispatch lifecycle end-to-end without LLM costs.

**Testable with**: Run `legion-agent` locally, dispatch a job via API, see the result come back.

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ A: Agent Process         │  │ B: Core Tool Plugins     │  │ C: Tests                 │
│                          │  │ (parallel with A)        │  │ (as items complete)      │
│ • agent_runner/main.py   │  │ • core/kubernetes/       │  │                          │
│ • WebSocket client       │  │   - pod status           │  │ • Agent process tests    │
│ • Job receive loop       │  │   - pod logs             │  │ • Tool unit tests        │
│ • Reconnection logic     │  │   - describe resource    │  │ • Plugin discovery tests │
│ • AgentRunnerConfig      │  │   - events               │  │ • End-to-end job loop    │
│ • Instrument with        │  │ • core/database/ (new)   │  │   (mock LLM)             │
│   telemetry spans        │  │ • core/network/ (extend) │  │                          │
│ • Mock executor (no LLM) │  │ • All use @tool decorator│  │                          │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘
```

**Validation checkpoint**: Before proceeding to B2, confirm:
- Agent connects to API, receives `job_dispatch`, sends `job_started` and `job_result`
- Reconnection works (kill API, restart, agent reconnects and resumes)
- `reassign_disconnected` reverts in-flight jobs when agent drops
- Core tool functions work standalone (unit tests pass against real/mocked infrastructure)

### Milestone B2: The Brain (LangGraph integration)

**Goal**: Replace the mock executor with a real LangGraph ReAct loop. The agent thinks, calls tools, and returns intelligent results.

**Testable with**: Dispatch a job, see the agent investigate your cluster and return a real analysis.

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ D: ReAct Loop            │  │ E: Plugin Discovery      │  │ F: Tests                 │
│                          │  │ + Tool Adapter           │  │                          │
│ • agents/graph.py        │  │ (parallel with D)        │  │ • Graph tests (mocked)   │
│   (LangGraph StateGraph) │  │                          │  │ • Integration test with  │
│ • agents/evaluator.py    │  │ • Entry point discovery  │  │   mock LLM               │
│   (factual grounding)    │  │   in agents/tools.py     │  │ • Token budget tests     │
│ • agents/context.py      │  │ • StructuredTool adapter │  │ • Prompt injection test  │
│   (token budget — 31)    │  │ • legion-cli plugins     │  │   (verify tool intercept │
│                          │  │   list                   │  │    blocks destructive)   │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘
```

### Deliverables

1. **Agent process** — `legion-agent` entry point: WebSocket client, job receive/execute/result loop, reconnection with exponential backoff + jitter (capped at 5 min). Instrumented with OpenTelemetry spans. Emits AuditEvents for every tool call (Decision 42).
2. **ReAct loop** �� LangGraph `StateGraph` in `agents/graph.py`. Single graph for chat and event processing, parameterized at entry (see Decision 12). Job types INVESTIGATE and DIAGNOSE added (Decision 43).
3. **Capability-aware dispatch** — DispatchService matches pending jobs to idle agents using `required_capabilities` ⊆ `agent.capabilities` (Decision 40).
4. **Core tool plugins** — `core/kubernetes/`, `core/database/`, `core/network/` — all functions decorated with `@tool` from `plumbing/plugins.py`. Registered as entry points in `pyproject.toml`. These are the first plugins (Decision 27).
5. **Plugin discovery + tool adapter** — `agents/tools.py` discovers tools via `importlib.metadata.entry_points(group="legion.tools")`, adapts them to LangChain `StructuredTool`. Same mechanism for core and third-party plugins.
6. **Plugin CLI** — `legion-cli plugins list` shows all discovered tool plugins, their categories, and read-only/write classification.
7. **Config** — `AgentRunnerConfig` (API URL, registration token, agent group, model settings).
8. **Per-job token budget** (Decision 31) — `agents/context.py` enforces a configurable max token ceiling per job. Default 32k. Runaway ReAct loops are killed when the budget is exhausted. Cost control from day one, not Sprint D.
9. **AuditEvent foundation** (Decision 42) — `domain/audit_event.py`, `AuditEventRepository`, basic `AuditService.emit_tool_call()`. Every tool call during job execution emits an AuditEvent. Full sink integration in Sprint D.
10. **Message emission during job execution** (Decision 44) — Agent process creates Messages (`AGENT_FINDING`, `TOOL_SUMMARY`, `AGENT_PROPOSAL`) during job execution, sent to control plane via WebSocket. Control plane persists via `MessageService` and pushes to subscribed clients via `on_message_created` callback. `DispatchService` creates `SYSTEM_EVENT` messages on job lifecycle transitions.

### What to Watch For

- Agent is a surface — same dependency rules as CLI and Slack
- Credential isolation: kubeconfig, SSH keys, DB passwords stay local. Never sent to API.
- Core tools use `@tool` decorator from `plumbing/plugins.py` (metadata only, no AI imports). The adapter in `agents/tools.py` wraps them for LangChain. Other surfaces call core functions directly.
- Entry points in `pyproject.toml`: `[project.entry-points."legion.tools"]` — core tools are the first consumers of this mechanism
- Start with a mock LLM mode for testing the process loop without API costs
- Streaming: agents send `job_progress` messages for real-time updates
- Instrument tool calls with telemetry: `legion_tool_calls_total`, `legion_tool_duration_seconds`
- **LangGraph checkpointer**: Adapting LangGraph's checkpointer to DB-backed persistence via the services layer is non-trivial. The session-aware keying (chat sessions load history, triage jobs start fresh) requires careful mapping between LangGraph's checkpoint keys and Legion's session/job IDs. Budget extra time here.
- **Token budget**: Enforce in `agents/context.py` before B2 testing begins. A runaway ReAct loop during development can burn significant API credits with no value. The budget should be configurable per agent group via `PromptConfig` or `AgentRunnerConfig`.

---

## Sprint C: The Experience

**Goal**: Operators interact with agents through the Legion UI, Slack, webhooks, and CLI. The Legion UI is the primary interaction surface (Decision 45) — a session workspace where humans and agents collaborate with structured timelines, live streaming, and approval workflows. The Event model unifies all input sources. All human surfaces consume the same streaming API. The system is usable without Slack (Decision 36).

**Testable with**: Webhook + browser + running API + connected agent (no Slack required). Or: Slack workspace + browser + running API + connected agent.

### Work Items

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ A: Streaming API         │  │ B: Event Model +         │  │ C: Slack Integration     │
│                          │  │    Ingestion             │  │ (parallel with B)        │
│ • Client-facing WebSocket│  │ (parallel with A)        │  │                          │
│   /ws/sessions/{id}      │  │                          │  │ • Mount Bolt in          │
│ • SSE endpoint           │  │ • domain/event.py        │  │   api/main.py as ASGI    │
│   /sessions/{id}/stream  │  │ • domain/event_source_   │  │ • alert_listener.py      │
│ • Activity stream        │  │   config.py              │  │   Filter → Event → Job   │
│   /ws/activity            │  │ • EventService +         │  │ • chat_listener.py       │
│ • Bridges agent WS to    │  │   EventRouter            │  │   Session → query jobs   │
│   client WS/SSE          │  │ • EventRepository        │  │ • mention_listener.py    │
│                          │  │ • Source adapters         │  │ • Result posting to      │
│                          │  │   (alertmanager, generic) │  │   Slack threads          │
│                          │  │ • Webhook endpoints       │  │                          │
│                          │  │   POST /events/ingest/*   │  │                          │
│                          │  │ • Event source config     │  │                          │
│                          │  │   CRUD + CLI              │  │                          │
│                          │  │ • Dedup by fingerprint    │  │                          │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐
│ D: Legion UI              │  │ E: Tests                 │
│ (parallel with B, C)     │  │ (as items complete)      │
│                          │  │                          │
│ • React + TypeScript     │  │ • EventService unit      │
│   frontend app           │  │ • Source adapter tests   │
│ • Console tabs           │  │ • Webhook integration    │
│   (chat with agents)     │  │ • Dedup window tests     │
│ • Fleet dashboard        │  │ • Event → Job flow       │
│   (agents status)        │  │ • Slack alert → Event    │
│ • Activity feed          │  │   backward compat        │
│   (real-time agent work) │  │ • End-to-end: webhook    │
│ • Event stream view      │  │   → event → job → agent  │
│   (incoming events,      │  │   → result               │
│    status, dedup stats)  │  │                          │
│ • Job inspector          │  │                          │
└─────────────────────────┘  └─────────────────────────┘
```

### Deliverables

#### Streaming API (Foundation for All Surfaces)

1. **Client-facing WebSocket** — `/ws/sessions/{session_id}`: Clients connect to receive streaming tokens as the agent thinks. Bridges `job_progress` from agent WebSocket to client WebSocket.
2. **Activity stream** — `/ws/activity`: Real-time feed of all agent activity across the fleet. Jobs dispatched, progress, completed, failed. Agent status changes. Events ingested.
3. **SSE fallback** — `/sessions/{session_id}/stream`: Server-Sent Events for clients that can't use WebSocket (simpler integration, HTTP-compatible).

#### Event Model and Ingestion (Decision 34, 35)

4. **Event domain model** — `domain/event.py`, `domain/event_source_config.py`. Two-layer structure: raw envelope + normalized fields.
5. **EventService + EventRouter** — Ingest, normalize, deduplicate, route. Source adapter pattern.
6. **Source adapters** — Alertmanager and generic adapters in Sprint C. Additional adapters (Datadog, CloudWatch, PagerDuty, OpsGenie) in Sprint D.
7. **Webhook endpoints** — `POST /events/ingest/{source}` with per-source auth tokens. Event source config CRUD via API and CLI.
8. **Deduplication** — Fingerprint-based dedup within configurable window. Prevents duplicate triage jobs from chatty alerting systems.
9. **Event query API** — `GET /events`, `GET /events/{id}`, `GET /events/stats` for dashboard and audit.

#### Slack Integration (Optional — Decision 36)

10. **Slack Bolt as ASGI sub-app**: Mounted alongside FastAPI in `api/main.py`. Shared engine, services, repos. **Conditionally mounted** — skipped when Slack credentials are not configured.
11. **Event listeners** (`slack/listeners/`):
   - `alert_listener.py` — ALERT mode channels: evaluate filter rules, create Events → triage jobs
   - `chat_listener.py` — CHAT mode channels: get-or-create session by thread, create query jobs with agent affinity
   - `mention_listener.py` — `@legion` mentions in any channel
12. **Result posting**: Structured results to Slack thread. Streaming via `job_progress` messages.
13. **Existing incident commands preserved**: `/incident`, `/resolve` unchanged.

#### Legion UI — Primary Surface (React + TypeScript, Decisions 25, 44, 45)

14. **Session workspace** — The core view. Structured timeline rendered by `MessageType` — human questions, agent findings, tool summaries, proposals, and approvals are visually distinct. Scope display (cluster, service, agent group). Live streaming as the agent works (Messages pushed via WebSocket). Inline job status. Approval buttons for `AGENT_PROPOSAL` / `APPROVAL_REQUEST` messages. Human input for questions and context. Multiple sessions open simultaneously in tabs.
15. **Fleet dashboard**: All agents, their status (IDLE/BUSY/OFFLINE), current job, agent group health. Real-time updates via activity stream WebSocket.
16. **Event stream view**: Incoming events by source, status (received/routed/suppressed/deduplicated), severity. Dedup stats. Click-through to the session/job created by a routed event.
17. **Activity feed**: Real-time feed showing what every agent is doing — jobs, tool calls, results. "Agent prod-aks-1 is investigating crashlooping pods..." This is what makes people feel like they have a team of SREs working.
18. **Job inspector**: Click into any job to see the full reasoning chain — tool calls, AuditEvent trail, intermediate results, final answer, token usage, cost, latency. Accessible from session timeline or standalone.
19. **Incident workspace** (Sprint D foundation): Session workspace bound to an incident. Shows correlated events, severity, status. Multiple jobs visible. Full investigation + remediation flow in one place. Built in Sprint D on the session workspace foundation.

### Architecture: Streaming Data Flow

```
Legion UI ←── WebSocket ──→ API ←── WebSocket ──→ Agent
  (React)    /ws/sessions/    │    /ws/agents/
             /ws/activity     │
             Messages pushed  │    Agent sends Messages
             to UI as created │    (findings, summaries)
                              │
Slack    ←── Bolt events ──→  │
                              │
CLI      ←── HTTP polling ──→ │
```

Both Slack and the Legion UI consume the same streaming infrastructure. The API bridges agent-side Messages (findings, summaries) and `job_progress` events to client-side WebSocket/SSE connections. Messages are persisted via `MessageService` and pushed to subscribers. The activity stream is a separate broadcast channel for fleet-wide visibility.

### What to Watch For

- **Two WebSocket layers**: Agent WebSocket (`/ws/agents/`) is for job dispatch. Client WebSocket (`/ws/sessions/`, `/ws/activity`) is for streaming results to users. Don't conflate them.
- **Event model is the foundation** — build it before Slack integration. Slack alert listeners should create Events, not Jobs directly. This ensures the Slack path and webhook path share the same routing and dedup logic.
- **Slack is conditionally mounted** — when `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are not set, the Bolt sub-app is not mounted. All non-Slack functionality works. Test both modes.
- **Source adapter testing** — each adapter needs tests with real webhook payloads from the source system. Collect sample payloads during development.
- **Dedup window tuning** — too short and Alertmanager re-fires create duplicate jobs. Too long and legitimate new alerts are suppressed. Default 5 minutes, configurable per source.
- Slack Bolt and FastAPI share async event loop — use `AsyncApp`
- Chat channels: same thread = same session = same agent (session affinity)
- Rate limit handling on Slack API calls
- Legion UI state management: React Query or similar for REST data, raw WebSocket for streaming Messages
- **Message rendering**: The Legion UI must render different `MessageType` values distinctly — findings look different from proposals, tool summaries are collapsible, approval requests have action buttons. This is what makes it a workspace, not a chat window.
- The "aha moment" works without Slack now: `docker compose up`, configure a webhook, fire a test alert, watch the agent investigate in the Legion UI with a structured timeline

---

## Sprint D: Completeness

**Goal**: Round out the system for production use. Full CLI, persistent conversations, knowledge base, guardrails, observability.

**Testable with**: End-to-end integration tests, production-like deployment

### Work Items

```
┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ A: Full CLI              │  │ B: Conversation Memory   │  │ C: Knowledge Layer       │
│                          │  │ (parallel with A)        │  │ (parallel with B)        │
│ • channel-mapping CRUD   │  │ • agents/checkpointer.py │  │ • Git clone on boot      │
│ • filter-rule CRUD       │  │   DB-backed via services │  │ • Git pull at job start   │
│ • prompt-config upsert   │  │   Session-aware          │  │ • File-path + keyword    │
│ • session start/message  │  │                          │  │   search                 │
│ • job list/status        │  │                          │  │                          │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐  ┌─────────────────────────┐
│ D: Tool Interceptor +    │  │ E: Observability +       │  │ F: Watchdog Agents +     │
│    Policy Engine         │  │    Audit Sinks           │  │    Additional Adapters   │
│ (parallel with C)        │  │ (parallel with D)        │  │ (after B+C)              │
│                          │  │                          │  │                          │
│ • agents/                │  │ • LLMUsageService        │  │ • HTTP probes, TLS,      │
│   tool_interceptor.py    │  │ • LLMUsageRepository     │  │   DNS, synthetic txns    │
│ • Policy model + CRUD    │  │ • Cost estimation        │  │ • Self-generated events  │
│ • execution_mode enforce │  │ • Audit sink integration │  │   via POST /events/      │
│ • Human approval flow    │  │   (JSONL, webhook, Redis)│  │   ingest/generic         │
│ • Slack approve/deny     │  │ • Summary endpoints      │  │ • WatchdogConfig         │
│   (or Legion UI approve)  │  │ • GET /audit/events API  │  │ • Source adapters:        │
│ • Timeout → deny default │  │                          │  │   Datadog, CloudWatch,    │
│                          │  │                          │  │   PagerDuty, OpsGenie     │
└─────────────────────────┘  └─────────────────────────┘  └─────────────────────────┘

┌─────────────────────────┐  ┌─────────────────────────┐
│ G: Incident Correlation  │  │ H: Remediation + VERIFY  │
│ (after E)                │  │ (after D)                │
│                          │  │                          │
│ • Incident model enhanced│  │ • REMEDIATE job type     │
│   with correlation_key   │  │ • VALIDATE job type      │
│ • IncidentService gains  │  │ • VERIFYING state in     │
│   correlation logic      │  │   job lifecycle          │
│ • Event → Incident       │  │ • Closed-loop validation │
│   grouping by            │  │   (did the fix work?)    │
│   correlation_key        │  │                          │
│ • Incident dashboard     │  │                          │
└─────────────────────────┘  └─────────────────────────┘
```

### Deliverables

1. **Full CLI**: All fleet management commands, session interaction, job monitoring, event source config, policy management.
2. **Checkpointer**: DB-backed conversation persistence via services layer. Session-aware — chat sessions load history, triage jobs start fresh.
3. **Knowledge layer**: Git clone on boot, pull at job start, file-path + keyword search. Repo URL from agent group config.
4. **Tool interceptor + Policy engine** (Decisions 41, 42): Human-in-the-loop for destructive operations. Policy model with org/group/capability scoped rules. `execution_mode` on AgentGroup enforced by interceptor. Approval via Slack or Legion UI with configurable timeout (deny by default). Full AuditEvent trail for every approval request/grant/deny.
5. **Observability + Audit sinks**: LLM usage tracking, cost estimation, summary endpoints. Audit sink integration: PostgreSQL (default), JSONL, webhook, Redis Stream. `GET /audit/events` query API with cursor pagination.
6. **Watchdog agents**: External observers with HTTP/TLS/DNS tools. Self-generate events via `POST /events/ingest/generic` (using the Event model from Sprint C, not direct job creation).
7. **Additional source adapters**: Datadog, CloudWatch, PagerDuty, OpsGenie adapters. Each with payload validation and normalization tests against real sample payloads.
8. **Incident correlation** (Decision 39): Enhanced Incident model with `correlation_key`. `IncidentService` gains correlation logic — events with matching `correlation_key` within a time window are grouped into the same incident. Incident dashboard in Legion UI.
9. **Remediation + validation** (Decision 43): `REMEDIATE` and `VALIDATE` job types. `VERIFYING` state in job lifecycle for closed-loop validation ("I restarted the pod — let me check if it's healthy now").

---

## Future Work (Not Yet Sequenced)

These build on the core sprints. Each requires design resolution before scheduling.

### Near-Term (After Sprint D)

| Topic | Description | Depends On |
|:------|:------------|:-----------|
| **Security hardening** | API key auth, RBAC, secrets management, query policies | Sprint B (agents running) |
| **Deployment** | Docker Compose, single k8s, multi-cluster k8s | Sprint D (full feature set) |

### Long-Term

| Topic | Description |
|:------|:------------|
| **Plugin sandboxing** | Sandbox untrusted third-party plugins (core plugins are trusted) |
| **Multi-agent chat rooms** | Multiple agents in one conversation |
| **Agent slash commands** | Slash command architecture for agent interaction |
| **Context metadata** | Datadog tags, k8s labels, cloud resource tags |
| **Memory and dreaming** | Distributed shared memory, background analysis |
| **TUI** | Terminal UI for fleet management |

---

## Sprint Dependencies

```
         Phases 1-2 (done)
                │
         Sprint A: Foundation
         (rename, cleanup, CLI, health,
          Alembic, API key auth)
                │
         Sprint B1: The Skeleton
         (agent process, job loop,
          core tools, mock executor)
                │
         Sprint B2: The Brain
         (LangGraph, ReAct loop,
          plugin discovery, token budget)
           ╱              ╲
   Sprint C:            Sprint D:
   The Experience       Completeness
   (Event model,        (CLI, memory, knowledge,
    webhooks, Slack,     policy engine, interceptor,
    Legion UI)            incident correlation,
                         remediation, observability,
                         watchdog, more adapters)
```

Sprints C and D are independent after Sprint B2. They can be worked on simultaneously.

B1 → B2 is the key risk boundary. B1 validates the full job dispatch lifecycle without LLM costs. If B1 works cleanly, B2 is primarily a LangGraph integration task. If B1 reveals problems in the WebSocket protocol, reconnection, or job state machine, those are cheaper to fix before LLM complexity is added.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Consolidated from build-phases.md, 2026-03-20-planning.md. |
| 2026-03-29 | Replaced 10-phase structure with Sprints A-D (Decision 23). Vertical delivery slices optimized for fastest path to operator value. |
| 2026-03-29 | Sprint C expanded: Legion UI (React + TypeScript) alongside Slack (Decisions 24, 25). |
| 2026-03-29 | Sprint A: Added observability primitives (Decision 26). Sprint B: Plugin system with core tools as first plugins (Decision 27). |
| 2026-03-29 | Architecture review: Sprint A expanded with Alembic migrations (Decision 29) and API key auth (Decision 30). Sprint B split into B1 (skeleton) and B2 (brain) milestones to reduce risk. Per-job token budget (Decision 31) added to B2. Single-worker constraint documented. |
| 2026-03-29 | Event architecture: Sprint C expanded with Event model, EventService, webhook ingestion, source adapters, event source config CRUD (Decisions 34, 35). Slack made optional (Decision 36). Sprint D gains additional source adapters. Watchdog agents now create Events, not Jobs directly. |
| 2026-03-29 | Domain model refinement: Sprint A gains execution_mode on AgentGroup, Job schema additions (event_id, required_capabilities, expanded types). Sprint B gains capability-aware dispatch, AuditEvent foundation, INVESTIGATE/DIAGNOSE job types. Sprint D gains Policy engine, incident correlation, remediation/validation job types with VERIFYING state (Decisions 37-43). |
| 2026-03-29 | Session and UI elevation: Sprint A gains Message schema + MessageRepository (Decision 44). Sprint B gains message emission during job execution. Sprint C: Admin UI renamed to Legion UI as primary interaction surface (Decision 45). Session workspace view with structured timeline, typed messages, approval workflows. Incident workspace as Sprint D foundation. Deliverables renumbered. |
