# Services and Persistence

> Service interfaces, repository contracts, DI wiring, ORM tables, and data flow diagrams.

---

## 1. Service Interfaces

All services follow the established pattern: constructor-injected dependencies, callback-based outward communication, repository-backed persistence.

### 1.1 DispatchService

**File**: `services/dispatch_service.py`
**Dependencies**: `FleetRepository`, `JobRepository`, `SessionRepository`
**Callbacks**: `on_job_dispatched(Job, Agent)`, `on_no_agents_available(Job)`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `create_job` | `(org_id, agent_group_id, job_type, payload, session_id?) → Job` | Creates job in PENDING. Auto-creates session when `session_id` not provided. |
| `dispatch_pending` | `(agent_group_id) → list[tuple[Job, Agent]]` | Matches pending jobs to idle agents (capability-aware, Decision 40) |
| `complete_job` | `(job_id, result) → Job` | RUNNING → COMPLETED, agent → IDLE |
| `fail_job` | `(job_id, error) → Job` | RUNNING → FAILED, agent → IDLE |
| `cancel_job` | `(job_id) → Job` | PENDING/DISPATCHED/RUNNING → CANCELLED |
| `register_agent` | `(agent_group_id, name, capabilities?) → Agent` | Creates agent in IDLE |
| `heartbeat` | `(agent_id) → Agent` | Updates heartbeat timestamp |
| `reassign_disconnected` | `(agent_id) → list[Job]` | Reverts in-flight jobs to PENDING |

**Session auto-creation**: When `session_id` is not provided, `create_job` creates a new session with the appropriate `source_type` (e.g., `"triage"`) and assigns it to the job. Every job is observable and connectable through its session.

**Capability matching** (Decision 40): When matching pending jobs to idle agents within a group, `dispatch_pending` prefers agents whose `capabilities` superset includes the job's `required_capabilities`. If no capable agent is idle, the job stays PENDING. Empty `required_capabilities` matches any agent.

**Queue drain**: When an agent completes a job → transitions to IDLE → `dispatch_pending` checks for queued jobs in that agent group and dispatches immediately.

### 1.2 MessageService

**File**: `services/message_service.py`
**Dependencies**: `MessageRepository`
**Callbacks**: `on_message_created(Message)` (for streaming to WebSocket/SSE clients)

| Method | Signature | Description |
|:-------|:----------|:------------|
| `add_message` | `(session_id, author_type, author_id, message_type, content, metadata?, job_id?) → Message` | Creates a message in the session timeline |
| `list_by_session` | `(session_id, since?, message_type?, limit?, offset?) → list[Message]` | Session timeline with optional filtering |
| `list_by_job` | `(job_id) → list[Message]` | All messages related to a specific job |

**Streaming**: The `on_message_created` callback is the bridge to real-time delivery. When a message is created, the callback pushes it to all clients subscribed to that session's WebSocket/SSE stream. This is how the Legion UI renders the live timeline.

**Who creates messages**:
- **Surface layer** (API routes, Slack listeners) — creates `HUMAN_MESSAGE` when a user sends input
- **DispatchService** — creates `SYSTEM_EVENT` on job creation, dispatch, completion
- **Agent process** — creates `AGENT_FINDING`, `TOOL_SUMMARY`, `AGENT_PROPOSAL` during job execution (sent via WebSocket, persisted by control plane)
- **PolicyService** (Sprint D) — creates `APPROVAL_REQUEST`, records `APPROVAL_RESPONSE`

### 1.3 SessionService

**File**: `services/session_service.py`
**Dependencies**: `SessionRepository`, `FleetRepository`
**Callbacks**: `on_session_created(Session)`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `get_or_create` | `(org_id, agent_group_id, channel_id, thread_ts) → (Session, bool)` | Finds or creates session by Slack thread |
| `pin_agent` | `(session_id, agent_id) → Session` | Pins session to agent on first dispatch |
| `close_session` | `(session_id) → Session` | ACTIVE → CLOSED |
| `touch` | `(session_id) → Session` | Updates last_activity |

### 1.4 FilterService

**File**: `services/filter_service.py`
**Dependencies**: None (stateless)

| Method | Signature | Description |
|:-------|:----------|:------------|
| `evaluate` | `(message_text, rules) → FilterAction \| None` | First matching rule wins, None if no match |

Pure function: `(message, rules) → should_triage`. Filter rules sorted by priority descending, short-circuit on first match.

### 1.5 LLMUsageService

**File**: `services/llm_usage_service.py`
**Dependencies**: `LLMUsageRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `record` | `(job_id, model, provider, input_tokens, output_tokens, ...) → LLMUsage` | Creates usage record, computes estimated cost |
| `get_by_job` | `(job_id) → list[LLMUsage]` | All LLM calls for a job |
| `get_by_session` | `(session_id) → list[LLMUsage]` | All LLM calls across a session |
| `summarize` | `(org_id, agent_group_id?, since?, until?) → LLMUsageSummary` | Aggregated usage and cost |

**Cost estimation**: Maintains a pricing table mapping `(provider, model) → (input_price_per_1k, output_price_per_1k)`. Updated manually. Unknown models default to `estimated_cost_usd=0.0` with a warning log.

### 1.6 EventService

**File**: `services/event_service.py`
**Dependencies**: `EventRepository`, `FleetRepository`, `DispatchService`
**Callbacks**: `on_event_routed(Event, Job)`, `on_event_suppressed(Event)`, `on_event_deduplicated(Event, Event)`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `ingest` | `(org_id, source, raw_payload, source_config?) → Event` | Creates Event, runs adapter, checks dedup, routes |
| `get_by_id` | `(event_id) → Event \| None` | |
| `list_events` | `(org_id, source?, status?, since?, until?, limit?, offset?) → list[Event]` | Query events with filters |
| `get_by_fingerprint` | `(org_id, fingerprint, within_seconds?) → Event \| None` | Dedup lookup |

**Ingest flow** (updated per Decision 37 — Event is immutable, Job references Event):
1. Create Event with `status=RECEIVED`, `type`, `source`, `raw_payload`
2. Run source adapter → populate normalized fields (`severity`, `title`, `service`, `fingerprint`, `correlation_key`)
3. **Dedup check**: If `fingerprint` is not None, check for existing event with same fingerprint within `dedup_window_seconds`. If found → mark `DEDUPLICATED`, set `dedup_ref_id`, return early.
4. **Route**: Call `EventRouter.route(event, source_config)` → returns `agent_group_id` or None
5. If routed → mark `ROUTED`, create Job via `DispatchService.create_job(event_id=event.id)` — the Job references the Event, not the other way around
6. If no route and no filter match → stays `RECEIVED` (queryable, no job)
7. If filter explicitly suppresses → mark `SUPPRESSED`

### 1.6.1 EventRouter

**File**: `services/event_router.py`
**Dependencies**: `FleetRepository` (for filter rules)

| Method | Signature | Description |
|:-------|:----------|:------------|
| `route` | `(event, source_config?) → str \| None` | Returns `agent_group_id` or None |

**Routing evaluation order**:
1. If `EventSourceConfig.agent_group_id` is set → use it (explicit routing)
2. If severity-based routing rules exist for the org → evaluate against normalized `severity`
3. If filter rules exist → evaluate against `raw_payload` (stringified) or `title`
4. No match → return None (event stays RECEIVED)

The EventRouter is a pure function — no side effects, no persistence. It takes an event and config, returns a routing decision.

### 1.6.2 Source Adapters

**File**: `services/event_adapters.py`

Stateless functions that extract normalized fields from source-specific payloads:

```
adapter(raw_payload: dict, config: EventSourceConfig | None) → NormalizedFields
```

`NormalizedFields` is a simple dataclass: `severity`, `title`, `service`, `fingerprint` — all nullable.

| Adapter | Severity Source | Fingerprint Source | Title Source |
|:--------|:---------------|:-------------------|:-------------|
| `alertmanager` | `labels.severity` → mapped enum | `sha256(alertname + labels subset)` | `annotations.summary` or `alertname` |
| `datadog` | `alert_type` → mapped enum | `sha256(monitor_id + alert_type)` | `title` |
| `cloudwatch` | `NewStateValue` → mapped (`ALARM`→`high`, `OK`→`info`) | `sha256(AlarmName + Region)` | `AlarmName` |
| `pagerduty` | `severity` (CEF) → direct map | `sha256(incident_key)` | `description` |
| `opsgenie` | `priority` → mapped (`P1`→`critical`, ...) | `sha256(alertId)` | `message` |
| `slack` | None (use `default_severity` from config or filter rules) | `sha256(channel_id + ts)` | message text (truncated) |
| `generic` | None (use `default_severity`) | None (no dedup) or `sha256(raw_payload)` | None |

Adapters handle missing fields gracefully — if the expected field doesn't exist in the payload, the normalized field stays None. The `default_severity` from `EventSourceConfig` is applied as a fallback when the adapter returns None for severity.

### 1.7 AuditService

**File**: `services/audit_service.py`
**Dependencies**: `AuditEventRepository`, sink configuration
**Callbacks**: None (fire-and-forget, async flush)

| Method | Signature | Description |
|:-------|:----------|:------------|
| `emit` | `(audit_event) → None` | Buffer event for async flush to configured sinks |
| `emit_tool_call` | `(job_id, agent_id, tool_name, input, output, duration_ms) → None` | Convenience: creates AuditEvent with action=TOOL_CALL |
| `query` | `(org_id, job_id?, agent_id?, action?, since?, until?, limit?, offset?) → list[AuditEvent]` | Query audit trail with filters |
| `get_job_trail` | `(job_id) → list[AuditEvent]` | Full reasoning chain for a job |

**Architecture** (Decision 32 + Decision 42): In-process buffer, async flush to configured sinks (PostgreSQL, JSONL, webhook, Redis Stream). Audit writes never block the hot path. AuditEvents from agent tool calls are the highest-volume event type — they flow through the same sink infrastructure as service-level audit events.

### 1.8 ConnectionManager

**File**: `api/websocket.py`
**Note**: Lives in the API surface, not `services/`, because it manages WebSocket connections (a transport concern).

| Method | Signature | Description |
|:-------|:----------|:------------|
| `connect` | `(agent_id, websocket) → None` | Accept and register connection |
| `disconnect` | `(agent_id) → None` | Remove connection |
| `disconnect_all` | `() → None` | Cleanup on shutdown |
| `send_job_to_agent` | `(job, agent) → None` | Push job dispatch message |
| `is_connected` | `(agent_id) → bool` | Check connection status |

### 1.9 MessageBus (Redis Streams + Pub/Sub)

**File**: `services/message_bus.py`
**Dependencies**: Redis connection
**Required for all fleet deployments** (Decision 17).

The MessageBus uses two Redis primitives for two different purposes:

- **Redis Streams** — Durable, ack-tracked message delivery for commands and results. At-least-once semantics with consumer groups, pending entry lists (PEL), and replay on failure.
- **Redis Pub/Sub** — Fire-and-forget fanout for transient status broadcasts and live UI notifications. No backlog, no replay. If nobody is listening, the message is gone.

#### Interface

| Method | Signature | Description |
|:-------|:----------|:------------|
| `publish_command` | `(stream, message) → stream_message_id` | XADD to a Redis Stream. Returns the stream message ID for tracking. |
| `ack` | `(stream, consumer_group, message_id) → None` | XACK — scoped to stream + consumer group + message ID. |
| `read_pending` | `(stream, consumer_group, consumer_name) → list[Message]` | XREADGROUP — read new or claim pending entries. |
| `broadcast` | `(channel, message) → None` | PUBLISH to a Redis Pub/Sub channel. Fire-and-forget. |
| `subscribe` | `(channel, callback) → None` | SUBSCRIBE to a Redis Pub/Sub channel. |

#### Stream and Channel Topology

**Redis Streams** (durable, ack-tracked):

| Stream | Purpose | Consumer Group | Drained To |
|:-------|:--------|:---------------|:-----------|
| `job.dispatch.{agent_group_id}` | Job dispatch commands to agents | `control-plane` | N/A (consumed in real-time) |
| `job.results` | Job results from agents | `control-plane` | PostgreSQL (`jobs` table) |
| `llm.usage` | LLM token/cost records from agents | `control-plane` | PostgreSQL (`llm_usage` table) |
| `audit.events` | Audit events from all sources | `control-plane` | PostgreSQL (`audit_events`) + configured sinks |
| `agent.events` | Agent lifecycle events (registered, connected, disconnected, heartbeat_timeout) | `control-plane` | PostgreSQL (agent status) + audit log |

**Redis Pub/Sub** (transient, fire-and-forget):

| Channel | Purpose | Consumers |
|:--------|:--------|:----------|
| `agent.status` | Agent online/offline/idle/busy hints for dashboards | Admin UI activity stream, monitoring |
| `activity.feed` | Live fleet activity for real-time dashboard | Admin UI `/ws/activity` |
| `ui.notifications` | Ephemeral UI notifications (approval requests, alerts) | Admin UI, Slack bridge |

**Why the split**: Streams give you durability, consumer groups, and replay — essential for job dispatch where losing a message means losing work. Pub/Sub gives you low-latency fanout for things where missing a message means a dashboard is stale for one heartbeat cycle — acceptable.

#### Agent Status: Two Layers

Agent status affects both display (dashboards) and scheduling decisions (dispatch). These have different reliability requirements:

| Layer | Mechanism | Purpose | Backlog |
|:------|:----------|:--------|:--------|
| **Pub/Sub broadcast** | `agent.status` channel | Dashboard hints — "agent-1 went BUSY" | No — if nobody listens, it's gone |
| **Redis hash** | `agent:{agent_id}` key | Last heartbeat timestamp, current status, current job | Yes — always readable |
| **In-process registry** | `ConnectionManager` dict | Which agents are connected to this worker | No — process-local |
| **Stream event** | `agent.events` stream | Durable state transitions for audit and replay | Yes — ack-tracked |

**Scheduling reads the Redis hash and in-process registry**, not Pub/Sub. Pub/Sub is only for live UI updates. This means:

- If an agent goes offline and nobody is watching the dashboard, the scheduler still knows (heartbeat timeout → Redis hash check → agent marked offline → jobs reassigned)
- If the control plane restarts, it rebuilds agent state from PostgreSQL + Redis hashes, not from Pub/Sub history (which doesn't exist)

#### Dispatch Flow (End-to-End Delivery Guarantee)

```
1. DispatchService matches pending job to idle agent
2. DispatchService writes job to DB (status: DISPATCHED, agent_id set)
3. DispatchService XADDs command to job.dispatch.{agent_group_id}
   → { command_id: "cmd_123", job_id: "...", payload: "..." }

4. Delivery worker XREADGROUPs from the stream (consumer group: control-plane)
5. Worker looks up agent WebSocket in ConnectionManager
6. Worker sends over WebSocket:
   → { "type": "command", "command_id": "cmd_123", "job_id": "...", "payload": {...} }

7. Agent receives, sends app-level ack:
   ← { "type": "command_received", "command_id": "cmd_123" }

8. ONLY NOW: Worker XACKs the stream entry
   → If agent never acks (crash, network), entry stays in PEL
   → PEL scanner reclaims after timeout → retry or reassign

9. Agent begins work:
   ← { "type": "command_started", "command_id": "cmd_123" }

10. Agent completes:
    ← { "type": "command_completed", "command_id": "cmd_123", "result": {...} }

11. Control plane XADDs result to job.results stream
12. Result drain worker reads → persists to PostgreSQL → XACKs
```

**Critical rule: Do not XACK on WebSocket send.** XACK only after the agent explicitly acknowledges receipt (`command_received`), or the control plane has durably recorded that the specific connected agent session accepted ownership. Otherwise, a WebSocket send that silently fails (TCP buffer accepted, agent never processed) loses the message with no replay.

#### Idempotency

Redis Streams plus XACK gives pending tracking and replay, but if a consumer processes work and crashes before ack, the message will be delivered again. All consumers must handle duplicates:

| Mechanism | Where | How |
|:----------|:------|:----|
| **Command IDs** | Every dispatch message has a unique `command_id` | Agent checks "am I already executing this command?" before starting |
| **Job status check** | Agent receives `command` for job X | Agent checks job status — if already RUNNING or COMPLETED, ignores |
| **Idempotent result writes** | `job.results` consumer | Writer checks job status — if already COMPLETED, skips |
| **Stream message dedup** | PEL reclaim | Delivery worker checks if command was already acked before re-sending |

This is standard Redis Streams practice. The key insight: **Redis durability stops at the control plane, not the agent.** The app-level `command_received` / `command_started` / `command_completed` protocol extends the delivery guarantee across the WebSocket boundary to the agent process.

#### WebSocket Message Protocol (App-Level)

The WebSocket messages between control plane and agent carry explicit command lifecycle:

```json
// Control plane → Agent
{ "type": "command", "command_id": "cmd_123", "job_id": "job_456", "payload": {...} }

// Agent → Control plane
{ "type": "command_received", "command_id": "cmd_123" }
{ "type": "command_started", "command_id": "cmd_123" }
{ "type": "command_progress", "command_id": "cmd_123", "data": "..." }
{ "type": "command_completed", "command_id": "cmd_123", "result": {...} }
{ "type": "command_failed", "command_id": "cmd_123", "error": "..." }
```

The `command_id` is the correlation key that bridges Redis Stream message IDs (server-side) to WebSocket message tracking (agent-side). Without it, there is no way to close the ack loop.

**Why Redis**:
- WebSocket is ephemeral — process restart loses in-flight messages
- Redis Streams: at-least-once delivery with consumer groups, PEL, and replay
- Unacknowledged dispatches stay in PEL, reclaimed after timeout, retried or reassigned
- LLM usage and audit events buffered to avoid write amplification during ReAct loops
- Control plane drains streams into PostgreSQL asynchronously (Redis = hot state, PostgreSQL = cold state)

**Dev/prod parity**: Redis is included in `docker compose up`. Running without it would mean dev uses in-process messaging while production uses Redis — two different code paths that mask bugs. The only mode without Redis is `legion-slack` standalone (no fleet, no dispatch pipeline).

---

## 2. Repository Interfaces

### Design Decision: One Repository Per Aggregate (Decision 2)

Not one ABC per entity. Simple CRUD entities are grouped into a combined repository. Complex query patterns get dedicated repositories.

- **`FleetRepository`** — combined: Organization, AgentGroup, Agent, ChannelMapping, FilterRule, PromptConfig
- **`JobRepository`** — dedicated: complex queries (pending by group, reassign, status transitions)
- **`SessionRepository`** — dedicated: thread-based lookup, agent pinning
- **`LLMUsageRepository`** — dedicated: aggregation queries

If the combined repository becomes unwieldy, split it. First candidate: Agent lifecycle extraction when heartbeat write volume grows. Start simple.

### Implementation Pattern (Decision 21)

Each repository has an ABC and **one SQLAlchemy implementation**. No InMemory implementations.

- ABC defines the interface contract
- SQLAlchemy implementation works with both SQLite and PostgreSQL (dialect handled by engine)
- Tests use `sqlite:///:memory:` — fast, isolated, tests real ORM code
- Dev uses `sqlite:///legion.db` — file-backed, inspectable
- Production uses `postgresql://` — concurrent access, full SQL features

### 2.1 FleetRepository

**File**: `services/fleet_repository.py`
**Implementation**: `SQLAlchemyFleetRepository`

- **Organization**: `save_org`, `get_org`, `list_orgs`, `delete_org`
- **AgentGroup**: `save_agent_group`, `get_agent_group`, `list_agent_groups(org_id)`, `delete_agent_group`
- **Agent**: `save_agent`, `get_agent`, `list_agents(agent_group_id)`, `list_idle_agents(agent_group_id)`, `delete_agent`
- **ChannelMapping**: `save_channel_mapping`, `get_channel_mapping`, `get_channel_mapping_by_channel(channel_id)`, `list_channel_mappings(org_id)`, `delete_channel_mapping`
- **FilterRule**: `save_filter_rule`, `get_filter_rule`, `list_filter_rules(channel_mapping_id)`, `delete_filter_rule`
- **PromptConfig**: `save_prompt_config`, `get_prompt_config`, `get_prompt_config_by_agent_group(agent_group_id)`, `delete_prompt_config`

### 2.2 JobRepository

**File**: `services/job_repository.py`
**Implementation**: `SQLAlchemyJobRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(job) → None` | Upsert |
| `get_by_id` | `(job_id) → Job \| None` | |
| `list_pending` | `(agent_group_id) → list[Job]` | Status = PENDING |
| `list_by_agent` | `(agent_id) → list[Job]` | All jobs for agent |
| `list_by_session` | `(session_id) → list[Job]` | All jobs in a session |
| `list_active` | `(agent_group_id?) → list[Job]` | Non-terminal status |

### 2.3 SessionRepository

**File**: `services/session_repository.py`
**Implementation**: `SQLAlchemySessionRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(session) → None` | Upsert |
| `get_by_id` | `(session_id) → Session \| None` | |
| `get_active_by_thread` | `(channel_id, thread_ts) → Session \| None` | Slack thread lookup |
| `list_active` | `(agent_group_id?) → list[Session]` | Status = ACTIVE |

### 2.4 LLMUsageRepository

**File**: `services/llm_usage_repository.py`
**Implementation**: `SQLAlchemyLLMUsageRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(usage) → None` | Insert (append-only) |
| `list_by_job` | `(job_id) → list[LLMUsage]` | |
| `list_by_session` | `(session_id) → list[LLMUsage]` | |
| `list_by_agent` | `(agent_id, since?, until?) → list[LLMUsage]` | |
| `summarize` | `(org_id, agent_group_id?, since?, until?) → LLMUsageSummary` | Aggregation |

### 2.5 EventRepository

**File**: `services/event_repository.py`
**Implementation**: `SQLAlchemyEventRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(event) → None` | Upsert |
| `get_by_id` | `(event_id) → Event \| None` | |
| `get_by_fingerprint` | `(org_id, fingerprint, since) → Event \| None` | Dedup lookup within time window |
| `list_events` | `(org_id, source?, status?, since?, until?, limit?, offset?) → list[Event]` | Filtered query |
| `list_by_job` | `(job_id) → Event \| None` | Reverse lookup: which event produced this job |
| `count_by_status` | `(org_id, since?, until?) → dict[EventStatus, int]` | Dashboard metrics |

### 2.6 AuditEventRepository

**File**: `services/audit_event_repository.py`
**Implementation**: `SQLAlchemyAuditEventRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(audit_event) → None` | Insert (append-only) |
| `list_by_job` | `(job_id) → list[AuditEvent]` | Full reasoning chain for a job |
| `list_by_agent` | `(agent_id, since?, until?) → list[AuditEvent]` | Agent activity history |
| `query` | `(org_id, job_id?, agent_id?, action?, since?, until?, limit?, offset?) → list[AuditEvent]` | Filtered query |

### 2.7 MessageRepository

**File**: `services/message_repository.py`
**Implementation**: `SQLAlchemyMessageRepository`

| Method | Signature | Description |
|:-------|:----------|:------------|
| `save` | `(message) → None` | Insert (append-only) |
| `list_by_session` | `(session_id, since?, message_type?, limit?, offset?) → list[Message]` | Session timeline with optional filtering |
| `list_by_job` | `(job_id) → list[Message]` | All messages related to a specific job |
| `count_by_session` | `(session_id) → int` | Message count for pagination |

### 2.8 FleetRepository (Extended)

`FleetRepository` gains CRUD methods for `EventSourceConfig`:

- **EventSourceConfig**: `save_event_source_config`, `get_event_source_config`, `get_event_source_config_by_token(auth_token)`, `list_event_source_configs(org_id)`, `delete_event_source_config`

The `get_event_source_config_by_token` method is used by the webhook endpoint to authenticate and look up the source config in a single query.

### Tests

Tests use `sqlite:///:memory:` — real SQL, no fake implementations:

```python
@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    create_all(engine)
    return SQLAlchemyJobRepository(engine)
```

---

## 3. ORM Tables

All inherit from `plumbing.database.Base`. Use `DateTime(timezone=True)` for datetime columns. Add `_ensure_utc()` for SQLite support.

| Table | Row Class | Location |
|:------|:----------|:---------|
| `organizations` | `OrganizationRow` | `services/fleet_repository.py` |
| `agent_groups` | `AgentGroupRow` | `services/fleet_repository.py` |
| `agents` | `AgentRow` | `services/fleet_repository.py` |
| `channel_mappings` | `ChannelMappingRow` | `services/fleet_repository.py` |
| `filter_rules` | `FilterRuleRow` | `services/fleet_repository.py` |
| `prompt_configs` | `PromptConfigRow` | `services/fleet_repository.py` |
| `jobs` | `JobRow` | `services/job_repository.py` |
| `sessions` | `SessionRow` | `services/session_repository.py` |
| `llm_usage` | `LLMUsageRow` | `services/llm_usage_repository.py` |
| `events` | `EventRow` | `services/event_repository.py` |
| `event_source_configs` | `EventSourceConfigRow` | `services/fleet_repository.py` |
| `messages` | `MessageRow` | `services/message_repository.py` |
| `audit_events` | `AuditEventRow` | `services/audit_event_repository.py` |
| `policies` | `PolicyRow` | `services/fleet_repository.py` (Sprint D) |
| `incidents` | `IncidentRow` | `services/repository.py` |
| `slack_incident_state` | `SlackIncidentStateRow` | `slack/incident/persistence.py` |

---

## 4. Dependency Injection Wiring

**File**: `api/main.py` → `create_app()` lifespan

```
                    ┌── FleetRepository
DispatchService ────┤── JobRepository
                    └── SessionRepository (for auto-creating sessions)

                    ┌── SessionRepository
SessionService ─────┤
                    └── FleetRepository (shared instance)

                    ┌── EventRepository
EventService ───────┤── FleetRepository (for EventSourceConfig + filter rules)
                    ├── DispatchService (for job creation on routed events)
                    └── EventRouter (stateless routing logic)

EventRouter ─────── FleetRepository (for filter rules, stateless evaluation)

FilterService ────── (stateless, no deps)

LLMUsageService ──── LLMUsageRepository

MessageService ─────── MessageRepository

AuditService ───────── AuditEventRepository + sink config

MessageBus ────────── Redis (required for fleet deployments)

ConnectionManager ── (in-memory WebSocket tracking, bridges to MessageBus)
```

**FastAPI `Depends()`** accessors in `api/deps.py` read from `app.state`.

---

## 5. Data Flow Diagrams

### 5.1 Alert Channel → Event → Triage Job (Slack)

```
Slack message in alert channel
  → Slack Bolt listener (api/main.py)
  → FleetRepository.get_channel_mapping_by_channel(channel_id)
  → FilterService.evaluate(message_text, rules)
  → if TRIAGE:
    → EventService.ingest(org_id, source="slack", raw_payload={text, channel, ts, user})
      → SlackAdapter normalizes (title=text truncated, fingerprint=sha256(channel+ts))
      → Dedup check (fingerprint within window)
      → EventRouter.route() → agent_group_id from ChannelMapping
      → Event status: RECEIVED → ROUTED
      → DispatchService.create_job(org_id, ag_id, TRIAGE, payload, event_id=event.id)
    → DispatchService.dispatch_pending(ag_id)
    → ConnectionManager.send_job_to_agent(job, agent)
    → Agent executes, sends job_result
    → DispatchService.complete_job(job_id, result)
    → Post result to Slack thread
```

**Backward compatibility**: The Slack alert flow gains Event creation as an intermediate step. The observable behavior is identical — same triage jobs, same agent dispatch, same results in Slack threads. The difference is that every alert is now recorded in the events table, queryable independently from jobs. The Job references the Event via `event_id` (Decision 37) — Event stays immutable.

### 5.2 Webhook → Event → Triage Job (External Source)

```
POST /events/ingest/alertmanager
  Authorization: Bearer <event_source_auth_token>
  Body: { alertmanager webhook payload }

  → Validate auth token → look up EventSourceConfig
  → EventService.ingest(org_id, source="alertmanager", raw_payload, source_config)
    → AlertmanagerAdapter normalizes:
      severity = labels.severity → mapped enum (or default_severity from config)
      title = annotations.summary or alertname
      service = labels.service or labels.namespace
      fingerprint = sha256(alertname + labels subset)
    → Dedup check: EventRepository.get_by_fingerprint(org_id, fingerprint, within=300s)
      → If duplicate: Event status → DEDUPLICATED, dedup_ref_id set, return 200
    → EventRouter.route(event, source_config)
      → agent_group_id from EventSourceConfig (explicit routing)
    → Event status: RECEIVED → ROUTED
    → DispatchService.create_job(org_id, ag_id, TRIAGE, payload=title + raw context, event_id=event.id)
  → DispatchService.dispatch_pending(ag_id)
  → ConnectionManager.send_job_to_agent(job, agent)
  → Agent executes, sends job_result
  → DispatchService.complete_job(job_id, result)
  → Result available via API (GET /jobs/{id}), activity stream, Admin UI
  → If Slack is configured: optionally post to configured notification channel
```

**No Slack required**: The entire flow works without Slack. Results are accessible via the API, Admin UI activity stream, and audit log. Slack notification is additive, not required.

### 5.3 Chat Channel → Session Query

```
Slack message in chat channel
  → Slack Bolt listener
  → FleetRepository.get_channel_mapping_by_channel(channel_id) → mode=CHAT
  → SessionService.get_or_create(org_id, ag_id, channel_id, thread_ts)
  → MessageService.add_message(session_id, HUMAN, user_id, HUMAN_MESSAGE, text)
  → DispatchService.create_job(org_id, ag_id, QUERY, payload, session_id=session.id)
  → MessageService.add_message(session_id, SYSTEM, "system", SYSTEM_EVENT, "Job created", {job_id})
  → If session has pinned agent: dispatch to that agent
  → Else: dispatch to idle agent, SessionService.pin_agent(session_id, agent_id)
  → ConnectionManager.send_job_to_agent(job, agent)
  → Agent executes, streams findings:
    → MessageService.add_message(session_id, AGENT, agent_id, AGENT_FINDING, finding, {job_id})
    → MessageService.add_message(session_id, AGENT, agent_id, TOOL_SUMMARY, summary, {job_id})
  → DispatchService.complete_job(job_id, result)
  → Post result to Slack thread
```

### 5.4 API Session → Query (Legion UI / CLI)

```
POST /sessions { org_id, agent_group_id, scope? }
  → SessionService creates session (no Slack fields)
  → MessageService.add_message(session_id, SYSTEM, "system", SYSTEM_EVENT, "Session created", {scope})
  → Returns Session

POST /sessions/{id}/messages { content: "what's the replication lag?" }
  → Validate session ACTIVE
  → MessageService.add_message(session_id, HUMAN, user_id, HUMAN_MESSAGE, content)
  → DispatchService.create_job(org_id, ag_id, QUERY, payload, session_id)
  → dispatch_pending → send_job_to_agent
  → Agent streams findings as Messages (AGENT_FINDING, TOOL_SUMMARY)
  → on_message_created callback → push to WebSocket /ws/sessions/{id}
  → Legion UI renders live timeline
  → Returns Job (client listens on WebSocket for streaming or polls GET /jobs/{id})
```

---

## 6. Database Strategy

**PostgreSQL** for production: concurrent access from WebSocket connections, Slack handlers, CRUD routes.
**SQLite** for development and testing: `DATABASE_URL` defaults to `sqlite:///legion.db`.

The `plumbing/database.py` engine factory handles both dialects. `DatabaseConfig.url` switches via environment. Repository contract tests run against in-memory SQLite.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Consolidated from domains-and-apis.md, domain-model.md, decisions.md. MessageBus added. LLMUsageService/Repository added. cancel_job added to DispatchService. |
| 2026-03-29 | Updated repository pattern: dropped InMemory implementations (Decision 21). One SQLAlchemy impl per ABC, tests use sqlite:///:memory:. |
| 2026-03-29 | MessageBus rewritten: Redis Streams (durable, ack-tracked) + Pub/Sub (transient fanout) as separate primitives. Proper XACK semantics (stream + consumer group + message ID). Agent status two-layer model. End-to-end dispatch flow with app-level command_received ack before XACK. Idempotency mechanisms. command_id protocol. |
| 2026-03-29 | Event architecture: Added EventService, EventRouter, source adapters (Decisions 34, 35). Added EventRepository, EventSourceConfig to FleetRepository. New data flow diagram for webhook ingestion (5.2). Updated Slack alert flow to go through Event model (5.1). Updated DI wiring. |
| 2026-03-29 | Domain model refinement: DispatchService gains capability-aware dispatch (Decision 40). EventService ingest flow updated — Job references Event via event_id, no write-back (Decision 37). Added AuditService + AuditEventRepository (Decision 42). Updated ORM tables, DI wiring, data flow diagrams. |
| 2026-03-29 | Session and UI elevation: Added MessageService (1.2) and MessageRepository (2.7) for structured session timelines (Decision 44). Added messages ORM table. Updated DI wiring. Data flows 5.3 and 5.4 updated with message creation. Admin UI renamed to Legion UI (Decision 45). Service sections renumbered. |
