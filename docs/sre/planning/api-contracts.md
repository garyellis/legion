# API Contracts

> REST endpoints, WebSocket protocol, request/response schemas, and error handling. This is the definitive contract for all API consumers.

---

## Design Principles

1. **API-first.** All surfaces (CLI, Slack, Web UI, TUI) are clients of the same API. Design the API completely before designing any surface.
2. **Single writer.** The API is the single writer to the database. CLI never talks to the DB directly. This enforces consistent validation and business logic.
3. **Domain models as responses.** Response schemas are the Pydantic domain models directly. Request bodies use thin `*Create`/`*Upsert` schemas.
4. **FastAPI auto-generates OpenAPI/Swagger.** No separate OAS spec to maintain.

---

## 1. REST Endpoints

Base path: `/` (no prefix).

### 1.1 Organizations

| Method | Path | Request Body | Response | Status |
|:-------|:-----|:-------------|:---------|:-------|
| `POST` | `/organizations` | `OrganizationCreate` | `Organization` | 201 |
| `GET` | `/organizations` | — | `list[Organization]` | 200 |
| `GET` | `/organizations/{org_id}` | — | `Organization` | 200 / 404 |

### 1.2 Agent Groups

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/agent-groups` | — | `AgentGroupCreate` | `AgentGroup` | 201 |
| `GET` | `/agent-groups` | `org_id` (required) | — | `list[AgentGroup]` | 200 |
| `GET` | `/agent-groups/{ag_id}` | — | — | `AgentGroup` | 200 / 404 |

### 1.3 Agents

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/agents/register` | — | `AgentRegister` | `AgentRegistration` | 201 |
| `POST` | `/agents/{agent_id}/refresh` | — | `AgentRefresh` | `AgentRegistration` | 200 / 401 |
| `GET` | `/agents` | `agent_group_id` (required) | — | `list[Agent]` | 200 |
| `GET` | `/agents/{agent_id}` | — | — | `Agent` | 200 / 404 |
| `DELETE` | `/agents/{agent_id}` | — | — | — | 204 / 404 |

Registration and refresh use the registration token (not the API key). See Section 3.0.

### 1.4 Channel Mappings

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/channel-mappings` | — | `ChannelMappingCreate` | `ChannelMapping` | 201 |
| `GET` | `/channel-mappings` | `org_id` (required) | — | `list[ChannelMapping]` | 200 |
| `GET` | `/channel-mappings/{mapping_id}` | — | — | `ChannelMapping` | 200 / 404 |
| `DELETE` | `/channel-mappings/{mapping_id}` | — | — | — | 204 / 404 |

### 1.5 Filter Rules

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/filter-rules` | — | `FilterRuleCreate` | `FilterRule` | 201 |
| `GET` | `/filter-rules` | `channel_mapping_id` (required) | — | `list[FilterRule]` | 200 |
| `GET` | `/filter-rules/{rule_id}` | — | — | `FilterRule` | 200 / 404 |
| `DELETE` | `/filter-rules/{rule_id}` | — | — | — | 204 / 404 |

Regex validation on `pattern` — returns 422 on invalid regex.

### 1.6 Prompt Configs

| Method | Path | Request Body | Response | Status |
|:-------|:-----|:-------------|:---------|:-------|
| `PUT` | `/prompt-configs/{agent_group_id}` | `PromptConfigUpsert` | `PromptConfig` | 200 |
| `GET` | `/prompt-configs/{agent_group_id}` | — | `PromptConfig` | 200 / 404 |

Upsert semantics: creates if not exists, updates if exists.

### 1.7 Event Source Configs

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/event-sources` | — | `EventSourceConfigCreate` | `EventSourceConfig` | 201 |
| `GET` | `/event-sources` | `org_id` (required) | — | `list[EventSourceConfig]` | 200 |
| `GET` | `/event-sources/{config_id}` | — | — | `EventSourceConfig` | 200 / 404 |
| `PUT` | `/event-sources/{config_id}` | — | `EventSourceConfigUpdate` | `EventSourceConfig` | 200 / 404 |
| `DELETE` | `/event-sources/{config_id}` | — | — | — | 204 / 404 |
| `POST` | `/event-sources/{config_id}/rotate-token` | — | — | `EventSourceConfig` | 200 / 404 |

The `rotate-token` endpoint generates a new `auth_token` for the source config, invalidating the old one. Used when a webhook token is compromised.

Response includes the `auth_token` only on `POST` (create) and `rotate-token`. `GET` responses redact the token to `"***"`.

### 1.8 Event Ingestion

| Method | Path | Auth | Request Body | Response | Status |
|:-------|:-----|:-----|:-------------|:---------|:-------|
| `POST` | `/events/ingest/{source}` | `Authorization: Bearer <event_source_auth_token>` | Source-specific JSON | `Event` | 201 / 200 (dedup) / 401 / 422 |

**`{source}`** is one of: `alertmanager`, `datadog`, `cloudwatch`, `pagerduty`, `opsgenie`, `generic`.

**Authentication**: Uses the `auth_token` from `EventSourceConfig`, not the API key. This allows monitoring tools to POST events without having full API access.

**Response codes**:
- `201` — Event created and routed (or received, pending routing)
- `200` — Event deduplicated (fingerprint match within window). Body includes the original event.
- `401` — Invalid or missing auth token
- `422` — Payload validation failed for the specific source adapter

### 1.9 Events (read-only)

| Method | Path | Query Params | Response | Status |
|:-------|:-----|:-------------|:---------|:-------|
| `GET` | `/events` | `org_id` (required), `source?`, `status?`, `severity?`, `since?`, `until?` | `list[Event]` | 200 |
| `GET` | `/events/{event_id}` | — | `Event` | 200 / 404 |
| `GET` | `/events/stats` | `org_id` (required), `since?`, `until?` | `EventStats` | 200 |

`EventStats` returns counts by status and severity for dashboard widgets:
```json
{
  "total": 142,
  "by_status": { "RECEIVED": 3, "ROUTED": 120, "SUPPRESSED": 8, "DEDUPLICATED": 11 },
  "by_severity": { "critical": 5, "high": 22, "medium": 45, "low": 30, "info": 37, "unknown": 3 },
  "by_source": { "alertmanager": 80, "datadog": 42, "slack": 15, "generic": 5 }
}
```

### 1.10 Jobs (read-only — created by dispatch)

| Method | Path | Query Params | Response | Status |
|:-------|:-----|:-------------|:---------|:-------|
| `GET` | `/jobs` | `agent_group_id` (required) | `list[Job]` | 200 |
| `GET` | `/jobs/{job_id}` | — | `Job` | 200 / 404 |
| `POST` | `/jobs/{job_id}/cancel` | — | `Job` | 200 / 404 / 422 |

Jobs are created internally by `DispatchService` (via Slack listeners, webhook events, or session messages), not by direct POST. This is intentional — job creation is a side effect of dispatch logic (or event routing), not a standalone CRUD operation.

### 1.11 Sessions

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/sessions` | — | `SessionCreate` | `Session` | 201 |
| `GET` | `/sessions` | `agent_group_id` (required) | — | `list[Session]` (active only) | 200 |
| `GET` | `/sessions/{session_id}` | — | — | `Session` | 200 / 404 |
| `POST` | `/sessions/{session_id}/messages` | — | `SessionMessage` | `Job` | 201 / 404 / 422 |
| `POST` | `/sessions/{session_id}/close` | — | `Session` | 200 / 404 / 422 |

The `/messages` endpoint:
1. Validates session is `ACTIVE` (422 if closed)
2. Creates a `QUERY` job via `DispatchService`
3. Dispatches pending jobs to connected agents via WebSocket
4. Returns the created Job (client polls `GET /jobs/{id}` for result or listens on WebSocket)

### 1.12 LLM Usage

| Method | Path | Query Params | Request Body | Response | Status |
|:-------|:-----|:-------------|:-------------|:---------|:-------|
| `POST` | `/llm-usage` | — | `LLMUsageCreate` | `LLMUsage` | 201 |
| `GET` | `/llm-usage` | `job_id` or `session_id` or `agent_id` or `agent_group_id` (at least one required) | — | `list[LLMUsage]` | 200 |
| `GET` | `/llm-usage/summary` | `org_id` (required), `agent_group_id?`, `since?`, `until?` | — | `LLMUsageSummary` | 200 |

### 1.13 Health

| Method | Path | Response | Status |
|:-------|:-----|:---------|:-------|
| `GET` | `/health` | `{ status: "ok", version: str }` | 200 |
| `GET` | `/health/ready` | `{ ready: bool, checks: {...} }` | 200 / 503 |

### Pagination

All list endpoints accept `?limit=N&offset=M` (default `limit=100`). Set the contract now so clients are built pagination-aware from the start.

---

## 2. Request Schemas

**File**: `api/schemas.py`

Domain models serve as response models directly. These are the POST/PUT request bodies:

```python
class OrganizationCreate:    { name: str, slug: str }
class AgentGroupCreate:      { org_id: str, name: str, slug: str, description?: str,
                               environment?: str, provider?: str, labels?: dict }
class AgentRegister:         { registration_token: str, name: str,
                               capabilities?: list[str], version?: str }
class AgentRefresh:          { registration_token: str }
class ChannelMappingCreate:  { org_id: str, channel_id: str, agent_group_id: str,
                               mode: ChannelMode }
class FilterRuleCreate:      { channel_mapping_id: str, pattern: str,
                               action: FilterAction, priority: int }
class PromptConfigUpsert:    { system_prompt: str, stack_manifest: str, persona: str }
class SessionCreate:         { org_id: str, agent_group_id: str }
class SessionMessage:        { payload: str }
class EventSourceConfigCreate: { org_id: str, name: str, source: str,
                                agent_group_id: str, default_severity?: EventSeverity,
                                field_mappings?: dict, dedup_window_seconds?: int,
                                enabled?: bool }
class EventSourceConfigUpdate: { name?: str, agent_group_id?: str,
                                default_severity?: EventSeverity,
                                field_mappings?: dict, dedup_window_seconds?: int,
                                enabled?: bool }
class LLMUsageCreate:        { job_id: str, model: str, provider: str,
                               input_tokens: int, output_tokens: int, total_tokens: int,
                               estimated_cost_usd?: float, latency_ms?: int,
                               tool_calls?: int }
```

---

## 3. WebSocket Protocol

### 3.0 Agent Registration (REST — before WebSocket)

Registration and connection are separate steps. The agent registers via REST first, then connects to the WebSocket with a short-lived session token.

**Endpoint**: `POST /agents/register`

```json
// Request
{
  "registration_token": "<agent-group-scoped token>",
  "name": "prod-aks-agent-1",
  "capabilities": ["kubernetes", "postgres"],
  "version": "0.1.0"
}

// Response (201)
{
  "agent_id": "<uuid>",
  "agent_group_id": "<uuid>",
  "session_token": "<short-lived JWT or opaque token>",
  "session_token_expires_at": "2026-03-29T12:30:00Z",
  "config": {
    "heartbeat_interval_seconds": 30,
    "websocket_path": "/ws/agents/<agent_id>"
  }
}
```

**How it works**:
1. Agent boots with a **registration token** (long-lived, scoped to an agent group, issued via CLI or API)
2. Agent calls `POST /agents/register` with the registration token + its metadata
3. Server validates the token, creates/updates the Agent record, returns an `agent_id` and a **short-lived session token**
4. Agent combines its configured control-plane base URL with `config.websocket_path`, then uses the session token to connect to the WebSocket (see 3.1)

**Re-registration**: If an agent restarts, it calls `/agents/register` again with the same registration token. The server can match by name + agent group to reuse the existing `agent_id` (avoiding orphaned records), or issue a new one.

**Token refresh**: The session token has a configurable TTL (default 1 hour). Before expiry, the agent calls `POST /agents/{agent_id}/refresh` with the registration token to get a new session token — no WebSocket interruption needed.

**Why separate from WebSocket**:
- Registration tokens never appear in WebSocket URLs, access logs, or proxy logs
- Registration is a one-time REST call with proper request/response semantics and error handling
- The WebSocket handshake stays simple — just present a short-lived session token
- Token rotation and refresh are standard REST operations, not shoehorned into WebSocket messages

### 3.1 WebSocket Connection

**Endpoint**: `wss://<host>/ws/agents/{agent_id}`

**Authentication**: Session token in the `Authorization` header (`Bearer <session_token>`). WebSocket clients that don't support custom headers (browser-based) can use `Sec-WebSocket-Protocol` as a fallback, but the agent process always uses the header.

**TLS required**: The WebSocket endpoint is `wss://` only. Plaintext `ws://` is rejected in production. Dev mode allows `ws://` when `LEGION_ALLOW_INSECURE_WS=true`.

**Connection lifecycle**:

1. Agent connects to `wss://<host>/ws/agents/{agent_id}` with `Authorization: Bearer <session_token>`
2. Server validates session token — rejects expired/invalid tokens with close frame (4001 Unauthorized)
3. Server verifies `agent_id` matches the token — rejects mismatches with close frame (4003 Forbidden)
4. Server accepts connection, registers in `ConnectionManager`, marks agent `IDLE`
5. Server dispatches any pending jobs for the agent's agent group
6. Normal operation: heartbeat, job dispatch, results (see 3.2, 3.3)
7. On disconnect: mark agent `OFFLINE`, revert in-flight jobs to `PENDING` via `reassign_disconnected()`

**Reconnection**: On disconnect, the agent reconnects with exponential backoff + jitter (cap 5 min). If the session token has expired, the agent calls `/agents/register` or `/agents/{id}/refresh` first, then reconnects with the new token.

### 3.2 Agent → Control Plane Messages

All messages are JSON with a `type` field. Command lifecycle messages carry `command_id` for correlation with Redis Stream tracking.

#### `heartbeat`
```json
{ "type": "heartbeat" }
```
Updates `agent.last_heartbeat`. Server responds with `heartbeat_ack`.

#### `command_received`
```json
{ "type": "command_received", "command_id": "cmd_123" }
```
**Critical**: This is the app-level ack. Only after receiving this does the control plane XACK the Redis Stream entry. Agent sends this immediately on receipt, before beginning execution.

#### `command_started`
```json
{ "type": "command_started", "command_id": "cmd_123" }
```
Transitions job `DISPATCHED → RUNNING`.

#### `command_completed`
```json
{ "type": "command_completed", "command_id": "cmd_123", "result": "<string>" }
```
Transitions job `RUNNING → COMPLETED`, agent `BUSY → IDLE`. Server checks for pending jobs and dispatches.

#### `command_failed`
```json
{ "type": "command_failed", "command_id": "cmd_123", "error": "<string>" }
```
Transitions job `RUNNING → FAILED`, agent `BUSY → IDLE`. Server checks for pending jobs and dispatches.

#### `command_progress`
```json
{ "type": "command_progress", "command_id": "cmd_123", "content": "<partial result>" }
```
Streaming partial results. Server forwards to Slack thread or WebSocket-connected UI for real-time updates. Best-effort — not persisted.

#### `llm_usage`
```json
{
  "type": "llm_usage",
  "command_id": "cmd_123",
  "job_id": "<uuid>",
  "model": "gpt-4o",
  "provider": "openai",
  "input_tokens": 1234,
  "output_tokens": 567,
  "total_tokens": 1801,
  "estimated_cost_usd": 0.023,
  "latency_ms": 2340,
  "tool_calls": 3
}
```
Creates an `LLMUsage` record via `llm.usage` stream. Server enriches with `session_id`, `agent_id`, `agent_group_id`, `org_id` from job/agent context.

#### `approval_request`
```json
{ "type": "approval_request", "request_id": "req_456", "command_id": "cmd_123",
  "tool": "kubectl_delete_pod", "args": {"namespace": "payments", "pod": "api-7f8b"},
  "reason": "Agent recommends restarting crashlooping pod" }
```
Agent requesting human approval for a destructive tool call. Routed to Slack/Admin UI.

### 3.3 Control Plane → Agent Messages

#### `command`
```json
{
  "type": "command",
  "command_id": "cmd_123",
  "job_id": "<uuid>",
  "job_type": "TRIAGE",
  "payload": "<string>",
  "session_id": "<uuid>",
  "prompt_config": {
    "system_prompt": "...",
    "stack_manifest": "...",
    "persona": "..."
  }
}
```
The `command_id` correlates this message to the Redis Stream entry. Includes `session_id` (always present) and `prompt_config` (looked up from agent group at dispatch time). Agent must respond with `command_received` before the control plane will XACK the stream entry.

#### `command_cancel`
```json
{ "type": "command_cancel", "command_id": "cmd_123" }
```
Cancel in-progress command. Agent should stop gracefully and send `command_failed` with a cancellation error.

#### `heartbeat_ack`
```json
{ "type": "heartbeat_ack" }
```

#### `approval_response`
```json
{ "type": "approval_response", "request_id": "req_456", "approved": true }
```
Response to an agent's `approval_request`. If no response within timeout, default is deny.

### 3.4 Client-Facing Streaming (Decision 24)

Separate from the agent WebSocket. These endpoints serve the Admin UI, CLI, and future integrations.

#### Session Stream — `/ws/sessions/{session_id}`

Client connects to receive real-time streaming tokens as an agent works on a job in that session.

**Server → Client Messages**:

```json
{ "type": "token", "content": "The pod", "job_id": "<uuid>" }
```
Streaming token from the agent's LLM response.

```json
{ "type": "tool_call", "tool": "get_pod_status", "args": {"namespace": "payments", "pod_name": "api-7f8b"}, "job_id": "<uuid>" }
```
Agent is invoking a tool — visible in the UI as "Running get_pod_status..."

```json
{ "type": "tool_result", "tool": "get_pod_status", "result": "CrashLoopBackOff (OOMKilled)", "job_id": "<uuid>" }
```
Tool returned a result.

```json
{ "type": "job_complete", "job_id": "<uuid>", "result": "..." }
```
Final result. Session remains open for follow-up messages.

**Client → Server Messages**:

```json
{ "type": "message", "payload": "show me the logs for that pod" }
```
Creates a new job in the session (equivalent to `POST /sessions/{id}/messages`). The agent picks it up with full conversation context.

#### SSE Fallback — `/sessions/{session_id}/stream`

Server-Sent Events for clients that can't use WebSocket. Same message types as above, encoded as SSE `data:` fields. Read-only — client sends messages via `POST /sessions/{id}/messages`.

#### Activity Stream — `/ws/activity`

Fleet-wide real-time activity feed. The Admin UI fleet dashboard connects here.

**Server → Client Messages**:

```json
{ "type": "agent_status", "agent_id": "<uuid>", "agent_name": "prod-aks-1", "status": "BUSY", "agent_group": "prod-aks" }
```

```json
{ "type": "job_dispatched", "job_id": "<uuid>", "job_type": "TRIAGE", "agent_name": "prod-aks-1", "agent_group": "prod-aks", "summary": "Investigating crashlooping pods" }
```

```json
{ "type": "job_progress", "job_id": "<uuid>", "agent_name": "prod-aks-1", "content": "Running kubectl get pods -n payments..." }
```

```json
{ "type": "job_completed", "job_id": "<uuid>", "agent_name": "prod-aks-1", "duration_ms": 12400, "tool_calls": 5 }
```

**Query params**: `?agent_group_id=<id>` to filter by group. Without filter, streams all activity for the org.

### 3.5 Transport Design Considerations

These are design directions for the WebSocket transport layer:

- **Backpressure awareness**: Client-side buffer limits, server push limit control, ack-based flow. Prevents memory blow-up and slow consumer collapse.
- **Multiplexed channels**: Logical channels (logs, metrics, commands, heartbeats, file transfer) over a single WebSocket connection. Reduces network cost of multiple connections and TLS handshakes. Message format: `{ "channel": "<name>", "data": {...} }`.
- **Structured workflow streaming**: Stream step-by-step partial results, reasoning traces. Makes the system feel alive. WebSocket to UI enables this as well.
- **Heartbeat and timeout**: Ping/pong at regular intervals. Missed heartbeats trigger disconnect detection.
- **Reconnection**: Exponential backoff with jitter, capped at max interval (e.g., 5 minutes).
- **Delivery guarantees**: Ack protocol, message replay buffer, connection state recovery built on top of WebSocket. Redis Streams provide at-least-once delivery for job dispatch.
- **Binary protocol**: Evaluate MessagePack or Protobuf for smaller payloads and faster parsing at scale. JSON is sufficient for initial phases.
- **Session affinity**: Needed for stability when multiple control plane instances run behind a load balancer.

---

## 4. Error Handling

### Exception Hierarchy

```
LegionError (plumbing/exceptions.py)
 └── ServiceError (services/exceptions.py)
      ├── IncidentCreationError
      ├── OrchestrationError     (step: str, retryable: bool)
      ├── DuplicateError
      ├── DispatchError
      ├── AgentNotFoundError
      ├── SessionError
      ├── FilterError
      └── UsageTrackingError
```

### API Error Mapping

**File**: `api/errors.py`

`ServiceError` subtypes map to HTTP status codes:

| Exception | HTTP Status |
|:----------|:------------|
| `AgentNotFoundError` | 404 |
| `DuplicateError` | 409 |
| `SessionError` | 422 |
| `DispatchError` | 503 |
| `FilterError` | 422 |
| General `ServiceError` | 500 |

---

## 5. Authentication (Decisions 18, 30, 35)

Four auth mechanisms for four trust boundaries:

| Consumer | Auth Method | Credential | Sprint |
|:---------|:------------|:-----------|:-------|
| **CLI / Admin UI** | `X-API-Key` header | Shared API key from `LEGION_API_KEY` env var | Sprint A (Decision 30) |
| **Agent registration** | Registration token in `POST /agents/register` body | Per-agent-group token, issued via CLI or API | Sprint A (Decision 18) |
| **Agent WebSocket** | `Authorization: Bearer <session_token>` header | Short-lived session token from registration response | Sprint A |
| **Event webhooks** | `Authorization: Bearer <event_source_auth_token>` header | Per-source token from `EventSourceConfig` | Sprint C (Decision 35) |
| **Slack** | Bolt signing secret | Managed by Slack SDK | Already working |

**API key** (`LEGION_API_KEY`): Gates all REST endpoints except `/health`, `/health/ready`, `/docs`, `/openapi.json`, `/agents/register` (which uses its own registration token), and `/events/ingest/*` (which uses event source tokens). When not set, auth is disabled (dev mode). This is a shared secret, not per-user identity. RBAC comes later.

**Registration token**: Long-lived, scoped to an agent group. Issued via `legion-cli fleet agent-group token <group>` or `POST /agent-groups/{id}/token`. Used only in the `POST /agents/register` request body — never in URLs, never in WebSocket handshakes, never in logs.

**Session token**: Short-lived (default 1 hour), returned by `/agents/register`. Used in the `Authorization` header on the WebSocket connection. Refreshable via `POST /agents/{id}/refresh` without disconnecting. If expired, agent re-registers to get a new one.

**Event source token**: Generated when creating an `EventSourceConfig`. Scoped to a single source configuration (one org, one adapter, one agent group). Used in the `Authorization` header on webhook POST requests. Rotatable via `POST /event-sources/{id}/rotate-token`. This gives monitoring tools the minimum credential needed — they can push events but cannot access fleet management, job data, or sessions.

**Why separate event source tokens**: Monitoring tools (Alertmanager, Datadog, etc.) should not need the API key. The event source token is narrowly scoped: it can only push events to one configured source, routed to one agent group. If compromised, rotate it without affecting API access or agent auth. If a monitoring tool is decommissioned, delete the source config — the token dies with it.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Consolidated from domains-and-apis.md, 2026-03-20-planning.md. Auto-registration removed. Job dispatch enriched with prompt_config and session_id. Cancel and close endpoints added. Pagination specified. |
| 2026-03-29 | Added client-facing streaming contracts (Decision 24): session WebSocket, SSE fallback, activity stream. |
| 2026-03-29 | Agent registration separated from WebSocket: two-step flow (REST register → WSS connect). Registration token in request body only, never in URLs. Short-lived session token for WebSocket auth via Authorization header. WSS required (TLS). Auth section updated with three-boundary model (API key, registration token, session token). |
| 2026-03-29 | WebSocket protocol rewritten with command_id lifecycle (command → command_received → command_started → command_completed). XACK tied to agent app-level ack, not WebSocket send. Added approval_request/response messages. |
| 2026-03-29 | Event architecture: Added event source config CRUD (1.7), event ingestion webhooks (1.8), event query endpoints (1.9). Added EventSourceConfigCreate/Update schemas. Renumbered Jobs→1.10, Sessions→1.11, LLM Usage→1.12, Health→1.13. (Decisions 34, 35, 36). |
