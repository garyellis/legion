# Security and Operations

> Secrets management, credential model, authentication, deployment, observability, and telemetry.

---

## 1. Credential Ownership Model

Credentials are classified into three categories with strict ownership rules.

### 1.1 Control-Plane-Integrated Credentials

Credentials strategically owned by the platform.

**Examples**: Model provider API keys, GitHub App private key

**Rules**:
- Centrally managed by the control plane
- Not automatically pushed to agents at registration
- Agents retrieve only what they need after authentication and authorization
- Prefer short-lived delegated tokens over distributing long-lived credentials
- Agents cache centrally issued credentials in memory when feasible
- Filesystem persistence of centrally issued credentials should be avoided

### 1.2 Agent-Local Execution Credentials

Credentials used by the agent to access user-owned, environment-specific, or infrastructure-adjacent systems.

**Examples**: kubeconfig, SSH keys, PostgreSQL passwords, Redis auth, RabbitMQ, Elasticsearch, Kafka, user-defined API credentials

**Rules**:
- Remain local to the agent — never uploaded to or stored by the control plane
- The control plane knows only that the capability is configured, not the secret material
- Configured by the operator on the agent host or runtime environment

### 1.3 Ephemeral Delegated Credentials

Short-lived, job-scoped temporary access tokens.

**Examples**: GitHub installation tokens

**Rules**:
- Issued by the control plane on demand (e.g., GitHub App generates installation token)
- Scoped to the specific operation
- Expire automatically

### Default Rule

The control plane does not store or distribute long-lived infrastructure root credentials unless there is an exceptional, explicitly approved use case.

---

## 2. Secret Source Mechanisms

How secrets are provided to agents:

| Mechanism | Description |
|:----------|:------------|
| Environment variables | Standard 12-factor approach |
| Mounted files / volumes | Kubernetes secrets, config maps |
| Workload identity | In-cluster identity (Azure MI, GCP WI, AWS IRSA) |
| External secret manager | Vault, AWS Secrets Manager, Azure Key Vault |
| Control-plane issuance | For supported centrally managed credentials only |

---

## 3. Agent Targets and Capabilities

### Target Definitions

Agents declare targets they can reach. Targets are instances of well-known integration types:

```yaml
targets:
  postgres_main:
    type: postgres
    host: db.internal
    port: 5432
    database: app
    username: app_user
    password_source:
      type: env
      name: POSTGRES_MAIN_PASSWORD
    tls:
      enabled: true
      ca_file: /etc/legion/certs/postgres-ca.pem

  vendor_api:
    type: http
    base_url: https://api.vendor.internal
    auth:
      type: bearer
      token_source:
        type: env
        name: VENDOR_API_TOKEN
```

### Well-Known Integration Types

| Type | Examples |
|:-----|:---------|
| `kubernetes` | AKS, EKS, GKE, on-prem |
| `postgres` | PostgreSQL databases |
| `mysql` | MySQL databases |
| `redis` | Redis instances |
| `rabbitmq` | RabbitMQ |
| `elasticsearch` | Elasticsearch clusters |
| `kafka` | Kafka clusters |
| `http` | Generic HTTP/API endpoints |
| `aws` | AWS services (broad) |
| `azure` | Azure services (broad) |
| `datadog` | Datadog API |
| `grafana` | Grafana API |
| `github-actions` | GitHub Actions |
| `harness-cd` | Harness CD |

Not all targets need their own secrets. For example, Inspektor Gadget relies on k8s service account and role binding.

### Capability Reporting

Agents report capabilities to the control plane. The status endpoint distinguishes configured targets from installed/runtime capabilities:

```json
{
  "capabilities": {
    "kubernetes": ["stage-cluster", "prod-cluster"],
    "postgres": ["payments-db"],
    "redis": ["cache-main"],
    "github": ["org-default"],
    "models": ["openai-default"]
  },
  "health": {
    "stage-cluster": "configured",
    "prod-cluster": "configured",
    "payments-db": "configured"
  }
}
```

**Must not expose**: Secret values, raw secret names, sensitive file paths, backend secret identifiers.

---

## 4. Secret Protection During Execution

Protecting secrets is critical to prevent credential exposure.

### Requirements

- Redaction mechanism prevents sensitive data from leaking in:
  - Job payloads and results
  - Audit logs
  - Chat sessions and Slack messages
  - Git commit messages (knowledge base PRs)
  - LLM context windows
- Build an abstraction for credentials without impeding the agent's ability to perform tool calls
- Jobs target logical targets/capabilities, not secret references

### Design Principles

- **Targets are instances** (e.g., `postgres_main`)
- **Capabilities are classes of function** (e.g., `postgres`)
- The control plane does not depend on agent-local secret names, file paths, or backend identifiers

---

## 5. Authentication (Phased)

### Phase 1: Sprint A Authentication (Decisions 18, 30)

Three auth mechanisms for three trust boundaries, all implemented in Sprint A:

| Consumer | Method | Credential |
|:---------|:-------|:-----------|
| CLI / Admin UI | `X-API-Key` header on REST requests | Shared API key from `LEGION_API_KEY` env var |
| Agent registration | Registration token in `POST /agents/register` body | Per-agent-group long-lived token |
| Agent WebSocket | `Authorization: Bearer <session_token>` header | Short-lived token from registration response |
| Slack | Bolt signing secret | Managed by Slack SDK |

**API key middleware** in `api/auth.py`. When `LEGION_API_KEY` not set, auth disabled (dev mode). Exempt paths: `/health`, `/health/ready`, `/docs`, `/openapi.json`, `/agents/register`.

**Agent two-step auth**: Agent registers via REST with registration token (never in URLs) → receives short-lived session token → connects to WSS with session token in Authorization header. See [API Contracts](./api-contracts.md) Section 3.0.

### Phase 2: Role-Based Access

| Role | Permissions |
|:-----|:------------|
| Admin | Full CRUD, agent management, config |
| Operator | Read fleet status, interact with sessions, view jobs |
| Read-only | View status, view job results |

### Phase 3: User Identity (Admin UI)

Options: GitHub OAuth, Google OAuth, Microsoft Entra SSO, generic OIDC/SAML.

Start with API key auth (same as CLI). Add OAuth/SSO as a dedicated effort after core functionality works.

---

## 6. Inter-Agent Query Policies

Cross-agent queries are governed by an allowlist policy. **Deny by default**.

```python
class QueryPolicy(BaseModel):
    id: str
    org_id: str
    source_agent_group_id: str    # Who is asking
    target_agent_group_id: str    # Who is being asked
    allowed: bool = True          # Explicit allow
```

**Example policies**:

| Source | Target | Allowed | Rationale |
|:-------|:-------|:--------|:----------|
| prod-aks | prod-db | Yes | Prod agents can query each other |
| staging-aks | staging-db | Yes | Staging agents can query each other |
| watchdog | prod-aks | Yes | Watchdog can trigger prod investigation |
| dev-aks | prod-aks | **No** | Dev must not access prod |

**Cycle prevention**: Jobs carry a `depth` field (default 0). Each inter-agent query increments depth. Rejected beyond configurable max (default 3).

---

## 7. Observability and Telemetry (Decision 26)

Intentional metrics and traces, not auto-instrumented noise. Implementation in `plumbing/telemetry.py`. See Decision 26 for the full metric inventory.

### 7.1 Infrastructure

- **Prometheus** — Counters, histograms, gauges exported at `/metrics`. Scraped by Prometheus, visualized in Grafana.
- **OpenTelemetry** — Spans at service boundaries. Trace context propagated in WebSocket `job_dispatch` so agent spans connect to control plane spans. One trace from Slack message to final result.
- **Zero-cost when disabled** — No-op stubs when `TELEMETRY_ENABLED=false`. No SDK initialization, no background threads. Preserves `docker compose up` simplicity.

### 7.2 LLM Usage Tracking

- One `LLMUsage` record per LLM API call (multiple per job as ReAct iterates)
- Token usage, estimated cost, latency, tool call count
- Aggregation: per job, session, agent, agent group, org
- Pricing table in config maps `(provider, model) → (input_price, output_price)`
- Prometheus metrics: `legion_llm_tokens_total`, `legion_llm_cost_usd_total`, `legion_llm_latency_seconds`

### 7.3 Audit Log (Decision 32)

The audit log is a **first-class subsystem**, not a side-effect of other features. It is the single structured record of everything that happened in the system — who did what, when, to what, and why. It is designed as its own sink with pluggable outputs.

#### Audit Events

Every meaningful action produces an `AuditEvent` record:

| Category | Events | Source |
|:---------|:-------|:-------|
| **Fleet config** | org.created, org.deleted, agent_group.created, agent_group.deleted, channel_mapping.created, prompt_config.updated | API routes |
| **Agent lifecycle** | agent.registered, agent.connected, agent.disconnected, agent.heartbeat_timeout | DispatchService, ConnectionManager |
| **Job lifecycle** | job.created, job.dispatched, job.started, job.completed, job.failed, job.cancelled, job.reassigned | DispatchService |
| **Session lifecycle** | session.created, session.pinned, session.closed | SessionService |
| **Tool execution** | tool.called, tool.completed, tool.failed, tool.approval_requested, tool.approval_granted, tool.approval_denied | Tool adapter, ToolInterceptor |
| **Inter-agent queries** | query.requested, query.dispatched, query.completed, query.denied_by_policy | DispatchService, QueryPolicy |
| **Auth events** | auth.success, auth.failure, auth.key_invalid | Auth middleware |
| **LLM calls** | llm.called, llm.completed, llm.budget_exhausted | Agent graph |

#### Audit Event Schema

```python
class AuditEvent(BaseModel):
    id: str                          # UUID
    timestamp: datetime              # UTC
    event_type: str                  # e.g. "job.dispatched"
    actor_type: str                  # "agent", "operator", "system", "slack"
    actor_id: str                    # Agent ID, user identifier, or "system"
    org_id: str | None               # Organization context
    agent_group_id: str | None       # Agent group context
    resource_type: str | None        # "job", "session", "agent", "tool", etc.
    resource_id: str | None          # ID of the affected resource
    context: dict                    # Job ID, session ID, tool name, etc.
    detail: str | None               # Human-readable description
    outcome: str                     # "success", "failure", "denied", "timeout"
```

#### Audit Sink Architecture

The audit log is a **write-only append stream** with pluggable output sinks. Events are written to a local buffer and flushed to configured sinks asynchronously.

```
Service / Middleware / Agent
        │
        ▼
   AuditService.emit(event)
        │
        ▼
   ┌─────────────┐
   │ Audit Buffer │  (in-process, bounded queue)
   └──────┬──────┘
          │ async flush
          ▼
   ┌──────────────────────────────────────────┐
   │           Configured Sinks                │
   │                                           │
   │  ┌──────────┐  ┌───────┐  ┌───────────┐ │
   │  │PostgreSQL │  │ File  │  │  Webhook  │ │
   │  │ (default) │  │(JSONL)│  │ (SIEM/S3) │ │
   │  └──────────┘  └───────┘  └───────────┘ │
   └──────────────────────────────────────────┘
```

**Sinks**:

| Sink | Description | Priority |
|:-----|:------------|:---------|
| **PostgreSQL** | `audit_events` table, queryable, default sink | Sprint A |
| **Structured log (JSONL)** | File-based, rotatable, zero-infrastructure | Sprint A |
| **Webhook** | POST events to external endpoint (SIEM, S3, Splunk, Elastic) | Sprint D |
| **Redis Stream** | High-throughput buffer for real-time consumers | When Redis is available |

**Design principles**:
- Audit writes MUST NOT block the hot path. If a sink is slow or down, events buffer and retry. If the buffer fills, events are dropped with a counter metric (`legion_audit_events_dropped_total`) — never block the operation being audited.
- Audit events are **immutable**. No updates, no deletes. Append-only.
- The PostgreSQL sink enables direct querying for investigations: "show me everything agent X did in the last hour" or "who changed the prompt config for prod?"
- The JSONL sink enables `jq` workflows and ship-to-S3 patterns with zero infrastructure.
- The webhook sink enables integration with enterprise SIEM systems (Splunk, Elastic, Sentinel, Datadog Log Management) — the audit log becomes a feed, not just a database table.

#### Querying the Audit Log

```
GET /audit/events?actor_id=agent-1&since=2026-03-29T00:00:00Z
GET /audit/events?event_type=tool.called&resource_id=job-123
GET /audit/events?org_id=acme&event_type=auth.failure
```

Pagination via cursor (not offset). Filterable by all fields in `AuditEvent`.

#### What This Enables

- **Incident forensics**: "What did the agent do in the 5 minutes before this outage?"
- **Compliance**: Immutable record of all automated actions on infrastructure
- **SIEM integration**: Webhook sink → Splunk/Elastic/Sentinel for correlation with other security events
- **Cost attribution**: Combine audit events with LLM usage records for per-job, per-agent cost allocation
- **Trust building**: Operators can see exactly what the agent did, not just the final answer

Inter-agent queries are fully auditable as Jobs in the database with corresponding audit events. Tool calls additionally tracked via Prometheus metrics `legion_tool_calls_total` and `legion_tool_duration_seconds`.

### 7.4 High-Value Dashboards

| Dashboard | Content | Data Source |
|:----------|:--------|:------------|
| **Fleet health** | Agents online/offline, agent group coverage, job queue depth | Prometheus + Admin UI activity stream |
| **Activity stream** | Real-time feed: jobs dispatched, completed, failed | Admin UI `/ws/activity` (Decision 24) |
| **Cost/usage** | Token spend over time, by agent group, by agent | Prometheus + LLMUsageService summaries |
| **Triage outcomes** | Alerts triaged, incidents created, resolution time | Prometheus + database queries |

### 7.5 Agent Status Reporting

Agents report rich status beyond heartbeat:

- Git connectivity (knowledge repo reachable?)
- Model connectivity (LLM endpoint healthy?)
- Installed plugins and available tools
- Custom prompts loaded
- Configured targets (names only)

---

## 8. Deployment

### 8.1 All-in-One (Development / POC)

`docker compose up` → API (control plane), agent, database. Working system in one command.

### 8.2 Production Architecture

```
┌────────────────────────────────────────┐
│ Control Plane                           │
│ • legion-api (FastAPI + Slack Bolt)     │
│ • PostgreSQL                            │
│ • Redis (optional)                      │
└────────────────┬───────────────────────┘
                 │ WebSocket
    ┌────────────┼────────────┐
    │            │            │
┌───┴──┐    ┌───┴──┐    ┌───┴──┐
│Agent │    │Agent │    │Watch-│
│(prod)│    │(dev) │    │ dog  │
│ k8s  │    │ k8s  │    │      │
└──────┘    └──────┘    └──────┘
```

### 8.3 Deployment Targets

| Target | Use Case | Priority |
|:-------|:---------|:---------|
| Docker Compose | Local dev, onboarding, POC | First |
| Single k8s cluster | Production-like testing | Second |
| Multi-cluster k8s | True distributed fleet | Third |

### 8.4 Entry Points

| Script | Module | Purpose |
|:-------|:-------|:--------|
| `legion-cli` | `legion.main:main` | CLI (Typer) |
| `legion-slack` | `legion.slack.main:main` | Standalone Slack bot |
| `legion-api` | `legion.api.main:main` | Combined API + Slack + fleet |
| `legion-agent` | `legion.agent_runner.main:main` | Data-plane agent |
| `legion-slack-manifest` | `legion.slack.manifest:main` | Generate Slack app manifest |

---

## 9. Messaging Architecture and WebSocket Reliability (Decision 33)

The control plane communicates with agents over persistent WebSocket connections. This section defines the reliability guarantees, failure modes, and the evolution path from single-worker to Redis-backed multi-worker.

### 9.1 Connection Lifecycle

**Step 1: Registration (REST)**

```
Agent                                     Control Plane
  │                                            │
  │──── POST /agents/register ────────────────→│
  │     { registration_token, name,            │
  │       capabilities, version }              │
  │                                            │  → validate token
  │                                            │  → create/update Agent record
  │←── 201 { agent_id, session_token,  ───────│  → session_token TTL: 1h
  │          config, websocket_url }           │
```

**Step 2: WebSocket Connection (WSS)**

```
Agent                                     Control Plane
  │                                            │
  │──── WSS CONNECT /ws/agents/{agent_id} ────→│
  │     Authorization: Bearer <session_token>  │
  │                                            │  → validate session_token
  │←── 101 Switching Protocols ────────────────│  → mark agent IDLE
  │                                            │
  │←── job_dispatch { job_id, payload, ... } ──│  (if pending jobs exist)
  │                                            │
  │──── heartbeat (every 30s) ────────────────→│  → update last_heartbeat
  │←── heartbeat_ack ─────────────────────────│
  │                                            │
  │    ... job execution ...                   │
  │                                            │
  │──── job_started { job_id } ───────────────→│  → job DISPATCHED → RUNNING
  │──── job_progress { job_id, data } ────────→│  → bridge to client WS/SSE
  │──── job_result { job_id, result } ─────────→│  → job RUNNING → COMPLETED
  │                                            │     → agent → IDLE
  │                                            │     → dispatch_pending()
  │                                            │
  │──── DISCONNECT (clean or crash) ──────────→│  → reassign_disconnected()
```

**Token refresh** (before session token expiry):

```
Agent                                     Control Plane
  │                                            │
  │──── POST /agents/{id}/refresh ────────────→│
  │     { registration_token }                 │
  │                                            │  → validate registration token
  │←── 200 { session_token, expires_at } ─────│  → new session_token
  │                                            │
  │  (no WebSocket interruption needed)        │
```

**Key security properties**:
- Registration token only appears in POST request bodies — never in URLs, headers, or logs
- Session token is short-lived (1h default) — limits blast radius if leaked
- WSS (TLS) required in production — plaintext `ws://` rejected unless `LEGION_ALLOW_INSECURE_WS=true`
- Agent ID in the URL path is not a secret — the session token is the credential

### 9.2 Message Protocol

All WebSocket messages are JSON with a `type` field for routing. Command lifecycle messages carry a `command_id` that bridges Redis Stream tracking (server-side) to WebSocket delivery (agent-side).

```json
{"type": "command", "command_id": "cmd_123", "job_id": "...", "payload": {...}}
{"type": "command_received", "command_id": "cmd_123"}
{"type": "command_completed", "command_id": "cmd_123", "result": {...}}
{"type": "heartbeat", "agent_id": "agent-1", "timestamp": "..."}
```

**Message types** (control plane → agent):

| Type | Description | Idempotent | Ack Required |
|:-----|:------------|:-----------|:-------------|
| `command` | Dispatch a job to the agent. Carries `command_id` + `job_id` + payload. | Yes (by command_id — agent ignores if already executing) | Yes — agent must send `command_received` |
| `command_cancel` | Cancel in-progress command | Yes (by command_id) | No |
| `heartbeat_ack` | Heartbeat acknowledged | Yes | No |
| `approval_response` | Approve/deny destructive operation | Yes (by request_id) | No |

**Message types** (agent → control plane):

| Type | Description | Idempotent | Triggers XACK |
|:-----|:------------|:-----------|:--------------|
| `heartbeat` | Liveness signal | Yes | No |
| `command_received` | Agent accepted the command — **this triggers XACK** on the dispatch stream | Yes (by command_id) | **Yes** |
| `command_started` | Agent began executing | Yes (by command_id) | No |
| `command_progress` | Streaming intermediate results | No (append-only) | No |
| `command_completed` | Job completed successfully, includes result | Yes (by command_id) | No |
| `command_failed` | Job failed with error | Yes (by command_id) | No |
| `llm_usage` | Token usage record for a single LLM call | No (append-only) | No |
| `approval_request` | Agent requesting human approval for destructive op | Yes (by request_id) | No |

**The `command_id` is critical.** It is the correlation key that connects: Redis Stream message ID (server tracking) → WebSocket message (transport) → agent execution (processing). Without it, there is no way to close the ack loop across the Redis → control plane → WebSocket → agent boundary.

**XACK rule**: The control plane XACKs a dispatch stream entry **only** after receiving `command_received` from the agent — not on WebSocket send. A WebSocket send that silently fails (TCP buffer accepted, agent process crashed before reading) would lose the message with no replay if acked prematurely. See [Services and Persistence](./services-and-persistence.md) Section 1.6 for the full dispatch flow.

### 9.3 Failure Modes and Recovery

| Failure | Detection | Recovery | Data Loss |
|:--------|:----------|:---------|:----------|
| **Agent crash** | Heartbeat timeout (configurable, default 90s) | Control plane marks agent OFFLINE, reverts in-flight jobs to PENDING, jobs reassigned to next idle agent | None — job persisted in DB before dispatch |
| **Agent network blip** | WebSocket close event | Agent reconnects with exponential backoff + jitter (cap 5min). Sends `agent_hello` on reconnect. Control plane re-registers, dispatches any pending jobs. | None — DB is source of truth. In-flight job either completed (result already sent) or reverted (heartbeat timeout). |
| **Control plane crash** | Agent WebSocket disconnects | All agents reconnect on backoff schedule. On restart, control plane loads state from DB. Agents re-register. Jobs in DISPATCHED/RUNNING without a connected agent are reverted after heartbeat timeout. | None — PostgreSQL is durable. |
| **Control plane restart** | Planned maintenance | Same as crash. Agents reconnect automatically. | None |
| **Split brain (agent thinks it's connected, CP disagrees)** | Heartbeat timeout on CP side | CP marks agent offline, reverts jobs. Agent eventually gets TCP RST or heartbeat_ack stops, triggers reconnect. | Possible duplicate work — agent may complete a job that was already reassigned. Mitigated by idempotent `job_result` (CP ignores result for jobs not in RUNNING for this agent). |

### 9.4 Delivery Guarantees

**Job dispatch**: At-least-once via Redis Streams. Jobs are persisted in the DB before dispatch. The command is XADDed to `job.dispatch.{agent_group_id}`. The delivery worker sends over WebSocket and waits for `command_received` from the agent before XACKing. If the agent never acks:
- The entry stays in the stream's pending entry list (PEL)
- A PEL scanner reclaims it after a configurable timeout (default 60s)
- The delivery worker retries or the job is reassigned
- The agent checks `command_id` on receipt — if already executing, it sends `command_received` again (idempotent)

**Job results**: At-least-once. The agent sends `command_completed` and the control plane XADDs to `job.results` stream, then drains to PostgreSQL. If the WebSocket drops mid-send, the agent re-sends on reconnect (idempotent by command_id). If the agent crashes before completing, heartbeat timeout → agent offline → job reverts to PENDING → reassigned. Work is lost but data isn't.

**Progress/streaming**: Best-effort. `command_progress` messages are not persisted — they flow through WebSocket and Pub/Sub only. If the connection drops mid-stream, the client loses partial output but gets the final result when the job completes. Acceptable: progress is a UX optimization, not a durability requirement.

**Idempotency**: All command lifecycle messages are idempotent by `command_id`. Duplicate delivery is safe — the agent checks current state before acting. The control plane checks job status before applying results. See [Services and Persistence](./services-and-persistence.md) Section 1.6 for the idempotency mechanisms.

### 9.5 Single-Worker Constraint (Pre-Redis)

**`ConnectionManager` is in-process.** It tracks active WebSocket connections in a Python dict. This means:

- **Single uvicorn worker only.** Multiple workers partition WebSocket connections. Worker A cannot dispatch a job to an agent connected to worker B.
- **No horizontal scaling of the control plane** until Redis backplane is implemented.
- Default config enforces `workers=1`. The API startup logs a warning if `workers > 1` and Redis is not configured.

This is acceptable for the current stage. A single FastAPI worker can handle hundreds of concurrent WebSocket connections. The bottleneck will be PostgreSQL write throughput, not WebSocket capacity.

### 9.6 Redis Backplane (When Scaling)

When horizontal scaling is needed, Redis Pub/Sub bridges WebSocket connections across workers:

```
                     ┌─── Worker 1 ───┐
Agent-A ──WS──────→  │ ConnectionMgr  │
                     │       ↕         │
                     │  Redis Pub/Sub  │ ←──────→ Redis
                     │       ↕         │
                     │ ConnectionMgr  │ ←──WS── Agent-C
                     └────────────────┘
                            ↕
                     ┌─── Worker 2 ───┐
Agent-B ──WS──────→  │ ConnectionMgr  │
                     │       ↕         │
                     │  Redis Pub/Sub  │ ←──────→ Redis
                     └────────────────┘
```

**How it works**:
1. `DispatchService` publishes `job_dispatch` to Redis Stream `job.dispatch.{agent_group_id}`
2. Each worker subscribes to all agent group streams
3. Worker checks if the target agent is connected locally — if yes, sends over WebSocket; if no, ignores (another worker has the connection)
4. Redis Streams provide at-least-once delivery with consumer groups and ack

**What flows through Redis** (Decision 17):
- Job dispatch notifications
- Agent status broadcasts
- Activity stream fan-out to client WebSocket connections
- Audit event buffering (Decision 32)
- LLM usage record buffering

**What stays in PostgreSQL**:
- All durable state: jobs, sessions, agents, config, audit events
- Redis is the message bus, not a data store. If Redis is wiped, the system recovers from PostgreSQL.

Redis is **required for all fleet deployments**, including local dev (`docker compose up`). This ensures the messaging path is identical in dev and production. See Decision 17.

### 9.7 Backpressure and Flow Control

| Scenario | Mechanism |
|:---------|:----------|
| **Agent overloaded** | One-job-at-a-time rule (Decision 16). Agent never receives a second job while one is running. |
| **Job queue growing** | Per-agent-group queue depth limit. Beyond limit, new jobs rejected with 429. Alert on `legion_job_queue_depth`. |
| **WebSocket buffer full** | TCP backpressure handles this naturally. If the agent can't consume fast enough, TCP flow control slows the sender. |
| **Client streaming overload** | Client WebSocket for progress/activity is fire-and-forget. Slow clients miss messages. The final `job_result` is always available via REST. |
| **Alert storm** | FilterService + debounce/dedup in Slack listener. IGNORE rules drop noise before job creation. Max pending jobs per agent group caps the queue. |

---

## 10. Graceful Degradation

The system works without AI. If the LLM is unreachable:

- Deterministic Slack commands (`/incident`, `/resolve`) continue working
- CLI commands that call `core/` directly are unaffected
- Only agent jobs (triage, query) require LLM connectivity
- Agents report model connectivity status; control plane can route accordingly

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Consolidated from 2026-03-20-planning.md Phases 3-4 and 8-10, decisions.md (14, 15, 19), domains-and-apis.md. |
| 2026-03-29 | Updated observability section: Prometheus + OpenTelemetry (Decision 26). Intentional metrics, not auto-instrumented noise. Dashboards reference Admin UI activity stream. |
| 2026-03-29 | Architecture review: Auth section updated for Sprint A (Decision 30). Agent auditing replaced with comprehensive audit log subsystem (Decision 32) — structured events, pluggable sinks (PostgreSQL, JSONL, webhook/SIEM), append-only, query API. Added Section 9: Messaging architecture and WebSocket reliability (Decision 33) — connection lifecycle, message protocol, failure modes, delivery guarantees, single-worker constraint, Redis backplane evolution, backpressure. |
