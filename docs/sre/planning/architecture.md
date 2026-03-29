# Architecture

> System topology, layer model, and component overview for the Legion SRE agent fleet.

---

## High-Level Topology

```
                    ┌─────────────────────────────────────────────────┐
                    │              Control Plane                       │
                    │  ┌─────────────────────────────────────────┐    │
                    │  │  Legion API (FastAPI + Slack Bolt ASGI) │    │
                    │  └──┬──────────┬──────────┬──────────┬─────┘    │
                    │     │          │          │          │          │
                    │  ┌──┴─────┐ ┌─┴──────┐ ┌─┴────────┐│          │
                    │  │PostgreSQL│ │ Redis  │ │ WebSocket ││          │
                    │  │(durable) │ │ (hot)  │ │ Manager   ││          │
                    │  └─────────┘ └────────┘ └───────────┘│          │
                    └──────────────────────────────────────────────────┘
                      ▲        ▲        ▲        ▲        ▲        ▲
                      │        │        │        │        │        │
              ┌───────┤  ┌─────┤  ┌─────┤  ┌─────┤  ┌─────┤  ┌─────┤
              │       │  │     │  │     │  │     │  │     │  │     │
         ┌────┴──┐┌───┴──┐┌───┴──┐┌───┴───┐┌───┴──┐┌───┴──┐
         │  CLI  ││Slack ││Web UI││Webhooks││Agent1││Agent2│
         │       ││(opt) ││      ││        ││(prod)││(dev) │
         └───────┘└──────┘└──────┘└────────┘└──────┘└──────┘
              Surfaces (input)               Data Plane Agents
```

**Control plane** — Single API process hosting FastAPI routes, Slack Bolt (ASGI sub-app, conditionally mounted), WebSocket handler, webhook ingestion endpoints, and all services. PostgreSQL for durable state. Redis for messaging durability and hot state.

**Surfaces** — Legion UI (primary, React + TypeScript), CLI, Slack (optional), Webhooks, TUI. The Legion UI is the primary interaction surface (Decision 45) — a session workspace where humans and agents collaborate with structured timelines, live streaming, and approval workflows. All surfaces are thin API clients: parse input, call API, format output. Webhooks push events via `POST /events/ingest/{source}`. The Legion UI connects to client-facing WebSocket/SSE for real-time Message streaming (Decision 44). The system is fully functional without Slack (Decision 36).

**Data plane** — Agent processes running in target environments (k8s clusters, database hosts, etc.). Connect to the control plane via agent WebSocket. Execute jobs using local tools and credentials.

---

## Layer Model

The fleet builds on the existing legion layer architecture. No new architectural concepts are introduced — the same layers, dependency rules, and patterns carry forward.

```
              ┌────────┬────────┬────────┬────────┬─────────────┐
              │  cli/  │ slack/ │  api/  │  tui/  │ agent-proc/ │   SURFACES
              └───┬────┴───┬────┴───┬────┴───┬────┴──────┬──────┘
                  │    ┌───┴────────┴───┐            │
                  │    │    agents/     │────────────┘         AI RUNTIME
                  │    └───────┬────────┘
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │   services/    │    │                 ORCHESTRATION
                  │    └───────┬────────┘    │
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │    domain/     │    │                 ENTITIES
                  │    └───────┬────────┘    │
                  └────────────┼─────────────┘
                       ┌───────┴────────┐
                       │     core/      │                     FOUNDATION
                       └────────────────┘
         ┌─────────────────────────────────────────┐
         │            plumbing/                     │         INFRASTRUCTURE
         └─────────────────────────────────────────┘
```

### Dependency Rules

```
plumbing/  → imports NOTHING from legion (only stdlib + pydantic-settings, sqlalchemy, apscheduler)
core/      → imports from plumbing/ only (plus stdlib + external SDKs)
domain/    → imports from plumbing/ and core models (type references, never logic)
services/  → imports from plumbing/, core/, domain/
agents/    → imports from plumbing/, core/, domain/, services/
surfaces   → import from any layer below
```

- No lateral imports between surfaces. `cli/` never imports from `slack/`.
- Callbacks flow upward (services → surfaces via injected callables). Imports flow downward.
- `core/` never imports LangChain, Rich, Slack SDK (except `core/slack/`), or FastAPI.
- Enforced by `tests/test_dependency_direction.py`.

---

## Component Overview

### Control Plane Components

| Component | Layer | Responsibility |
|:----------|:------|:---------------|
| **DispatchService** | `services/` | Job creation, capability-aware agent matching (Decision 40), job lifecycle, session auto-creation |
| **EventService** | `services/` | Event ingestion, normalization, dedup, routing to DispatchService |
| **EventRouter** | `services/` | Evaluate routing rules against events (stateless) |
| **MessageService** | `services/` | Structured session timeline — create messages, query by session/job, streaming callback (Decision 44) |
| **SessionService** | `services/` | Session lifecycle, get-or-create by thread, agent pinning |
| **FilterService** | `services/` | Evaluate filter rules against messages (stateless) |
| **LLMUsageService** | `services/` | Token/cost tracking, aggregation queries |
| **ConnectionManager** | `api/` | WebSocket connection registry, job push, heartbeat tracking |
| **MessageBus** | `services/` | Redis Streams + Pub/Sub for messaging durability (required for fleet) |
| **AuditService** | `services/` | Granular audit trail — per-tool-call AuditEvents, buffered async flush to sinks (Decision 42) |
| **PolicyService** | `services/` | Policy evaluation — execution mode enforcement, tool-level rules (Sprint D, Decision 41) |
| **FleetRepository** | `services/` | CRUD for Organization, AgentGroup, Agent, ChannelMapping, FilterRule, PromptConfig, EventSourceConfig, Policy |
| **EventRepository** | `services/` | Event persistence with fingerprint dedup and status queries |
| **JobRepository** | `services/` | Job persistence with status-based queries, capability matching |
| **SessionRepository** | `services/` | Session persistence with thread-based lookup |
| **MessageRepository** | `services/` | Append-only message persistence, session timeline queries (Decision 44) |
| **AuditEventRepository** | `services/` | Append-only audit event persistence, job trail queries |

### Data Plane Components

| Component | Layer | Responsibility |
|:----------|:------|:---------------|
| **Agent process** | Surface (`agent_runner/`) | WebSocket client, job receive/execute/result loop |
| **LangGraph ReAct loop** | `agents/` | Single StateGraph for chat and event processing |
| **Local tools** | `core/` | kubectl, psql, ssh, dns, http — plain Python, adapted for agent discovery |
| **Knowledge layer** | Git repo | Runbooks, stack manifests, known patterns — cloned on boot |

### The Agent Process is a Surface

The data-plane agent (`legion-agent`) follows the exact same pattern as CLI and Slack:
- Parses input (job payloads from WebSocket)
- Calls logic (agents/ ReAct loop → core/ tools)
- Formats output (structured results back over WebSocket)

It imports from `agents/`, `services/`, `domain/`, `core/`, and `plumbing/`. Same dependency rules.

---

## Interaction Patterns

| Pattern | Trigger | Flow | Example |
|:--------|:--------|:-----|:--------|
| **Deterministic** | CLI command or Slack slash command | Surface → `core/` directly | `vm-list`, `dns-check` |
| **Orchestrated** | Multi-step workflow | Surface → `services/` → multiple `core/` modules | Incident create → resolve |
| **Webhook triage** | External alert via webhook | `POST /events/ingest/{source}` → EventService → Event → DispatchService (capability-aware) → Agent | Alertmanager fires → agent with matching capabilities investigates |
| **Slack triage** | Message in alert channel matches filter | Slack → FilterService → EventService → Event → DispatchService → Agent | Slack alert channel → agent investigates |
| **Interactive session** | Message in chat channel, session API, or Legion UI | Surface → MessageService (HUMAN_MESSAGE) → SessionService → DispatchService → Agent → MessageService (AGENT_FINDING, TOOL_SUMMARY) → WebSocket push to UI | Operator interrogates infrastructure through agent |
| **Proactive** | Watchdog detects anomaly | Watchdog agent → `POST /events/ingest/generic` → Event → Agent | External monitoring → triage |

---

## Deployment Modes

| Mode | Entry Points | Slack | Database | Redis | Use Case |
|:-----|:-------------|:------|:---------|:------|:---------|
| **Demo** | `legion-api` (API only, no Slack) | No | SQLite | Redis | Try the product, PoC, evaluation. Webhooks + CLI + Legion UI. |
| **Simple** | `legion-slack` (standalone) | Yes | SQLite | No | Single-node incident bot, no fleet. No agents, no dispatch. |
| **Fleet (dev)** | `legion-api` (API + optional Slack) | Optional | SQLite | Redis | Local dev, `docker compose up`. Same messaging path as production. |
| **Fleet (production)** | `legion-api` (API + optional Slack) | Optional | PostgreSQL | Redis | Full distributed fleet |

Redis is **required for all fleet deployments**, including local dev. It is the messaging tier — job dispatch notifications, agent status broadcasts, activity stream fan-out, and audit event buffering all flow through Redis. Running without it means dev and production use fundamentally different messaging paths, which hides bugs that only surface in production.

`docker compose up` starts Redis alongside the API and database. The operational cost is trivial (single container, ~5MB RAM) and the consistency gain is significant.

**Slack is optional for fleet deployments** (Decision 36). When Slack credentials (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`) are not configured, the Bolt sub-app is not mounted. All other functionality — webhook event ingestion, API sessions, Legion UI, agent dispatch — works without Slack. This enables a "try it in 15 minutes" experience: `docker compose up`, configure a webhook, watch agents work.

The `legion-slack` standalone mode (no fleet, no agents) requires Slack by definition. It's a Slack bot, not a control plane.

The same services, repositories, and domain models power all modes. The difference is wiring in `main.py`.

---

## What Already Works (Inherited from Legion)

| Need | Current Codebase | Status |
|:-----|:-----------------|:-------|
| Database persistence | `plumbing/database.py` — shared `Base`, `create_engine()` | Ready |
| Config system | `plumbing/config/` — `LegionConfig` base, env var prefixes | Ready |
| Domain models | `domain/incident.py` — Pydantic models with state machine | Pattern established |
| Repository pattern | ABC + SQLAlchemy, tests on `sqlite:///:memory:` | Pattern established |
| Service layer with callbacks | `IncidentService` with injected callbacks | Pattern established |
| Slack surface with DI | `slack/main.py` — config, engine, repos, service, handlers | Pattern established |
| AI chains | `agents/chains/` — scribe, post-mortem; graceful degradation | Working |
| Dependency enforcement | `tests/test_dependency_direction.py` | Enforced |

---

## Tool Architecture and Plugin System (Decisions 22, 27)

Tools are capabilities that flow through the entire system. Core tools are the first plugins — external tools use the same mechanism.

```
plumbing/plugins.py              <- @tool decorator (metadata only, no AI imports)
  ↑ used by
core/kubernetes/pods.py          <- @tool decorated function (plain Python)
core/database/queries.py         <- @tool decorated function (plain Python)
third_party_package/             <- same @tool, same entry points
  ↑ discovered by
agents/tools.py                  <- entry point discovery → LangChain StructuredTool
  ↑ also consumed by
slack/commands/                  <- direct import from core/ (for slash commands)
api/routes/                      <- direct import from core/ (for REST endpoints)
cli/commands/                    <- direct import from core/ (for CLI commands)
```

**The `@tool` decorator** (`plumbing/plugins.py`) annotates metadata — category, read_only flag, description from docstring. It does NOT import LangChain or any AI framework. Every layer can import it.

**Entry point discovery** — tools register as `legion.tools` entry points in `pyproject.toml`. `agents/tools.py` discovers all installed tools via `importlib.metadata.entry_points()` and adapts them to LangChain `StructuredTool`. Third-party packages (`pip install legion-datadog-tools`) become available immediately.

**Non-agent surfaces** import `core/` directly — no plugin discovery needed for Slack commands, CLI, or API routes that use the same functions.

---

## Observability (Decision 26)

Intentional metrics and traces, not auto-instrumented noise.

```
plumbing/telemetry.py            <- Prometheus metrics + OpenTelemetry tracer
  ↑ imported by                     (no-ops when disabled, zero cost to import)
services/dispatch_service.py     <- legion_jobs_total, legion_job_duration_seconds
services/session_service.py      <- legion_sessions_active
agents/tools.py                  <- legion_tool_calls_total, legion_tool_duration_seconds
api/websocket.py                 <- legion_websocket_connections
  ↑ exported at
api/routes/metrics.py            <- /metrics (Prometheus scrape target)
```

Every metric is deliberately placed. Operators see fleet health and cost. Developers see tool performance and query latency. No noise.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version consolidated from architecture-fit.md, SLACK_SRE_ARCHITECTURE.md |
| 2026-03-29 | Added Tool Architecture section (Decision 22). Updated repository pattern reference (Decision 21). |
| 2026-03-29 | Expanded Tool Architecture to include plugin system (Decision 27). Added Observability section (Decision 26). |
| 2026-03-29 | Deployment modes updated: Redis required for all fleet deployments including dev (Decision 17 revised). Only legion-slack standalone skips Redis. |
| 2026-03-29 | Event architecture: Added EventService, EventRouter, EventRepository to component overview. Webhooks added to topology diagram as a surface. Interaction patterns updated with webhook triage and Slack triage as separate patterns. Deployment modes updated: Slack optional, Demo mode added (Decisions 34, 35, 36). |
| 2026-03-29 | Domain model refinement: Added AuditService, PolicyService, AuditEventRepository to component overview. DispatchService updated for capability-aware matching (Decision 40). Interaction patterns updated for capability routing. (Decisions 37-43). |
| 2026-03-29 | Session and UI elevation: Added MessageService and MessageRepository to component overview (Decision 44). Admin UI renamed to Legion UI throughout — elevated to primary interaction surface (Decision 45). Surfaces description updated. Interactive chat pattern renamed to "Interactive session" with Message flow. |
