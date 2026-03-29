# Domain Model

> All entities, relationships, state machines, and field definitions for the SRE agent fleet. This is the authoritative contract.

---

## Entity Relationship Map

```
Organization (tenant boundary)
 ├── AgentGroup (logical grouping, execution_mode: READ_ONLY/PROPOSE/REQUIRE_APPROVAL/AUTO_EXECUTE)
 │    ├── Agent (running process, state machine: IDLE/BUSY/OFFLINE, capabilities: [str])
 │    ├── PromptConfig (1:1 per agent group — system prompt, stack, persona)
 │    ├── Event (immutable input event, type: ALERT/WEBHOOK/SCHEDULE/MANUAL)
 │    ├── Session (conversational workspace, pinned to one agent)
 │    │    ├── Message (structured timeline: HUMAN_MESSAGE, AGENT_FINDING, TOOL_SUMMARY, ...)
 │    │    └── Job (unit of work — may reference Event or Session, has required_capabilities)
 │    │         └── AuditEvent (per tool call: action, input, output, duration)
 │    └── Incident (groups related Events and Jobs by correlation_key)
 │         └── Policy (execution rules: org/group/capability scoped)
 ├── EventSourceConfig (webhook config → agent group, per-source adapter)
 └── ChannelMapping (Slack channel → agent group, mode: ALERT or CHAT)
      └── FilterRule (regex pattern → triage trigger, ALERT mode only)
```

### Key Design Choice: AgentGroup (not ClusterGroup)

The original design used "ClusterGroup" which implied k8s clusters only. **AgentGroup** is the correct abstraction — it's any logical grouping of agents with a shared purpose:

- A k8s cluster (`prod-aks`)
- A database fleet (`prod-db`)
- An observability platform (`datadog-alerts`)
- A single-function specialist (`cert-watcher`)
- A broad-purpose environment (`staging-general`)

The `environment` and `provider` fields are optional metadata, not required structure. This enables limitless configurability: map an agent group to receive events from a specific system, give it a unique prompt, and assign it one job type.

---

## Key Relationships

| Parent | Child | Cardinality | FK on Child | Notes |
|:-------|:------|:------------|:------------|:------|
| Organization | AgentGroup | 1:N | `org_id` | |
| AgentGroup | Agent | 1:N | `agent_group_id` | |
| AgentGroup | PromptConfig | 1:1 | `agent_group_id` (unique) | |
| AgentGroup | Session | 1:N | `agent_group_id` | |
| Organization | ChannelMapping | 1:N | `org_id` | |
| ChannelMapping | FilterRule | 1:N | `channel_mapping_id` | |
| ChannelMapping | AgentGroup | N:1 | `agent_group_id` on mapping | |
| Session | Message | 1:N | `session_id` on Message | Structured timeline entries (Decision 44) |
| Session | Job | 1:N | `session_id` on Job | Every job belongs to a session |
| Message | Job | N:1 | `job_id` on Message | Nullable — human messages may not reference a job |
| Agent | Job | 1:N | `agent_id` on Job | Nullable until dispatched |
| Event | Job | 1:1 | `event_id` on Job | Nullable — not all jobs come from events (Decision 37) |
| Job | Incident | N:1 | `incident_id` on Job | Nullable, set on triage outcome |
| Job | AuditEvent | 1:N | `job_id` on AuditEvent | Every tool call, decision, result (Decision 42) |
| Organization | EventSourceConfig | 1:N | `org_id` | |
| EventSourceConfig | AgentGroup | N:1 | `agent_group_id` on config | Default routing target |
| AgentGroup | Event | 1:N | `agent_group_id` on Event | Nullable until routed |
| Event | Event | N:1 | `dedup_ref_id` on Event | Self-ref for dedup chains |
| Incident | Event | 1:N | `correlation_key` match | Logical grouping, not FK (Decision 39) |
| Incident | Job | 1:N | `incident_id` on Job | Jobs linked to incident |
| Organization | Policy | 1:N | `org_id` on Policy | Execution rules (Decision 41) |

### Uniqueness Constraints

| Entity | Unique Fields | Rationale |
|:-------|:-------------|:----------|
| Organization | `slug` | Human-readable identifier |
| AgentGroup | `(org_id, slug)` | Unique within org |
| ChannelMapping | `channel_id` | One channel → one agent group |
| PromptConfig | `agent_group_id` | One config per agent group |

---

## Entities

All entities are Pydantic `BaseModel` subclasses in `legion/domain/`. ORM rows live in the service layer. Every field below is the contract.

### Organization

**File**: `domain/organization.py`

Tenant boundary. All resources scoped to an org. No state transitions — pure data.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `name` | `str` | required | Display name |
| `slug` | `str` | required | URL-safe identifier, unique |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

### AgentGroup

**File**: `domain/agent_group.py`

A logical grouping of agents with a shared purpose. The routing target for jobs. No state transitions — pure configuration.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `name` | `str` | required | Display name |
| `slug` | `str` | required | URL-safe, unique within org |
| `description` | `str` | `""` | Purpose of this group |
| `environment` | `str \| None` | `None` | Optional: `dev`, `staging`, `prod` |
| `provider` | `str \| None` | `None` | Optional: `aks`, `eks`, `gke`, `on-prem` |
| `labels` | `dict[str, str]` | `{}` | Arbitrary metadata tags |
| `execution_mode` | `ExecutionMode` | `READ_ONLY` | Trust level for agents in this group (Decision 41) |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**Enums**: `ExecutionMode`: `READ_ONLY`, `PROPOSE`, `REQUIRE_APPROVAL`, `AUTO_EXECUTE`

### Agent

**File**: `domain/agent.py`

A running agent process. Belongs to an agent group.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `agent_group_id` | `str` | required | FK → AgentGroup |
| `name` | `str` | required | Human-readable label |
| `status` | `AgentStatus` | `OFFLINE` | State machine (see below) |
| `current_job_id` | `str \| None` | `None` | Set when BUSY |
| `capabilities` | `list[str]` | `[]` | Reported by agent at connect |
| `last_heartbeat` | `datetime \| None` | `None` | Updated on heartbeat |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**State machine**:

```
         connect
OFFLINE ────────→ IDLE
  ↑                │  dispatch_to(job_id)
  │ disconnect     ↓
  ├─────────── BUSY
  │                │  complete / fail
  │                ↓
  └─────────── IDLE
```

**Methods**: `go_idle()`, `go_busy(job_id)`, `go_offline()`, `heartbeat()`

**Invariants**:
- `OFFLINE → IDLE` on connect
- `IDLE → BUSY` on dispatch (sets `current_job_id`)
- `BUSY → IDLE` on job complete/fail (clears `current_job_id`)
- `* → OFFLINE` on disconnect (clears `current_job_id`)

### Job

**File**: `domain/job.py`

A unit of work dispatched to an agent. Every job belongs to a session.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `agent_group_id` | `str` | required | FK → AgentGroup |
| `agent_id` | `str \| None` | `None` | Set on dispatch |
| `session_id` | `str` | required | FK → Session, always set |
| `event_id` | `str \| None` | `None` | FK → Event. Set when job originates from an event. Null for chat/manual jobs. (Decision 37) |
| `type` | `JobType` | required | See enum below |
| `status` | `JobStatus` | `PENDING` | State machine (see below) |
| `payload` | `str` | required | Message text or alert payload |
| `result` | `str \| None` | `None` | Set on completion |
| `error` | `str \| None` | `None` | Set on failure |
| `incident_id` | `str \| None` | `None` | FK → Incident (triage outcome) |
| `required_capabilities` | `list[str]` | `[]` | Capabilities needed to execute this job (Decision 40) |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |
| `dispatched_at` | `datetime \| None` | `None` | Set on dispatch |
| `completed_at` | `datetime \| None` | `None` | Set on complete/fail/cancel |

**Enums** (Decision 43):
- `JobType`: `TRIAGE`, `QUERY`, `INVESTIGATE`, `DIAGNOSE`, `SUMMARIZE`, `REMEDIATE`, `VALIDATE`
  - Sprint A: `TRIAGE`, `QUERY`
  - Sprint B: + `INVESTIGATE`, `DIAGNOSE`
  - Sprint C: + `SUMMARIZE`
  - Sprint D: + `REMEDIATE`, `VALIDATE`
- `JobStatus`: `PENDING`, `DISPATCHED`, `RUNNING`, `VERIFYING`, `COMPLETED`, `FAILED`, `CANCELLED`

**State machine** (Decision 43):

```
                dispatch_to(agent_id)         start()
PENDING ─────────────────────→ DISPATCHED ──────→ RUNNING
  │                               │                  │
  │ cancel()                      │ cancel()         ├── complete(result)
  ↓                               ↓                  │        ↓
CANCELLED                    CANCELLED           │   COMPLETED
                                                     │
                                                     ├── verify()        (optional, remediation jobs)
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

**VERIFYING is optional**: Investigation and query jobs go RUNNING → COMPLETED directly. Remediation jobs (Sprint D) may transition RUNNING → VERIFYING → COMPLETED to confirm the fix worked. Not all job types use it.

**Reassignment path** (agent disconnect): `DISPATCHED/RUNNING → PENDING` (agent_id cleared, dispatched_at cleared)

**Methods**: `dispatch_to(agent_id)`, `start()`, `complete(result)`, `verify()`, `fail(error)`, `cancel()`

**Every job has a session**: `session_id` is always set. For conversational queries, the caller provides the session. For standalone triage or one-shot jobs, `DispatchService.create_job()` auto-creates a session. This means:

- Every job is observable — you can see what an agent is doing by looking at its session
- Any session can be connected to interactively — an operator can attach to an in-progress triage session and talk to the agent while it works
- Sessions are the universal unit of agent interaction, whether initiated by a human, an alert, or a watchdog

### Session

**File**: `domain/session.py`

A conversational workspace between a user (or system) and an agent. Groups related jobs and messages into a persistent, interactive timeline. Pinned to a single agent for the duration. Sessions are the universal unit of agent interaction — whether initiated by a human question, an alert, or a watchdog. The Message entity (Decision 44) provides the structured timeline within each session.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `agent_group_id` | `str` | required | FK → AgentGroup |
| `agent_id` | `str \| None` | `None` | Pinned on first dispatch |
| `source_type` | `str \| None` | `None` | `"slack"`, `"api"`, `"cli"`, `"triage"` |
| `source_id` | `str \| None` | `None` | Slack channel ID, API client ID, etc. |
| `source_thread_id` | `str \| None` | `None` | Slack thread_ts, or null |
| `slack_channel_id` | `str \| None` | `None` | Current implementation (migration target: source_id) |
| `slack_thread_ts` | `str \| None` | `None` | Current implementation (migration target: source_thread_id) |
| `status` | `SessionStatus` | `ACTIVE` | |
| `created_at` | `datetime` | `utcnow()` | |
| `last_activity` | `datetime` | `utcnow()` | |

**Enums**: `SessionStatus`: `ACTIVE`, `CLOSED`

**Methods**: `pin_agent(agent_id)`, `touch()`, `close()`

**Surface decoupling note**: The `slack_channel_id`/`slack_thread_ts` fields work for Phase 4 (Slack integration). The `source_type`/`source_id`/`source_thread_id` fields are the intended migration target for surface-portable sessions. Both coexist during transition.

### ChannelMapping

**File**: `domain/channel_mapping.py`

Links a Slack channel to an agent group. One channel → one agent group. The `mode` determines how messages are handled.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `channel_id` | `str` | required | Slack channel ID, unique |
| `agent_group_id` | `str` | required | FK → AgentGroup |
| `mode` | `ChannelMode` | `ALERT` | `ALERT` or `CHAT` |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**Enums**: `ChannelMode`: `ALERT`, `CHAT`

- **ALERT mode**: Filter rules evaluate incoming messages. Matches trigger triage jobs.
- **CHAT mode**: Every message becomes a query job routed through sessions with agent affinity.

### FilterRule

**File**: `domain/filter_rule.py`

Per-channel rules that decide what messages trigger triage jobs. Only applies to ALERT mode channels.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `channel_mapping_id` | `str` | required | FK → ChannelMapping |
| `pattern` | `str` | required | Regex pattern |
| `action` | `FilterAction` | `TRIAGE` | `TRIAGE` or `IGNORE` |
| `priority` | `int` | `0` | Higher = evaluated first |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**Enums**: `FilterAction`: `TRIAGE`, `IGNORE`

**Evaluation**: Sorted by `priority` descending. First match wins. No match = no action.

### PromptConfig

**File**: `domain/prompt_config.py`

System prompt, stack manifest, and persona for an agent group. One per agent group. Delivered in job payloads so agents always run with the latest configuration.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `agent_group_id` | `str` | required | FK → AgentGroup, unique |
| `system_prompt` | `str` | `""` | Base system prompt for agents |
| `stack_manifest` | `str` | `""` | "Payment-API → Redis → Postgres" |
| `persona` | `str` | `""` | "PostgreSQL Expert" |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

### Event

**File**: `domain/event.py`

An immutable input event from any source — monitoring alerts, Slack messages, webhooks, API calls. Two-layer structure: raw envelope (always present) and normalized fields (best-effort, all nullable). Events are the input stream; Jobs are the work stream. See Decisions 34, 37.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `type` | `EventType` | required | What kind of trigger (Decision 37) |
| `source` | `str` | required | Who sent it: `alertmanager`, `datadog`, `cloudwatch`, `pagerduty`, `opsgenie`, `slack`, `api`, `generic` |
| `source_id` | `str \| None` | `None` | Source system's ID for this event |
| `raw_payload` | `dict` | required | Full JSON as received, untouched |
| `fingerprint` | `str \| None` | `None` | Derived hash for dedup (source + key fields) |
| `correlation_key` | `str \| None` | `None` | Groups related events — e.g., same service outage (Decision 37). Foundation for Incident grouping (Decision 39). |
| `severity` | `EventSeverity \| None` | `None` | Mapped by source adapter |
| `title` | `str \| None` | `None` | Extracted summary |
| `service` | `str \| None` | `None` | Affected service name |
| `status` | `EventStatus` | `RECEIVED` | Write-once routing state (see below) |
| `agent_group_id` | `str \| None` | `None` | Set on routing — FK → AgentGroup |
| `dedup_ref_id` | `str \| None` | `None` | FK → Event (original event, when deduplicated) |
| `created_at` | `datetime` | `utcnow()` | |

**Enums**:
- `EventType`: `ALERT`, `WEBHOOK`, `SCHEDULE`, `MANUAL` (Decision 37)
- `EventSeverity`: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`
- `EventStatus`: `RECEIVED`, `ROUTED`, `SUPPRESSED`, `DEDUPLICATED`

**Immutability**: Events are immutable after creation. The `status` and `agent_group_id` fields are write-once — set during the routing step immediately after creation, never changed again. The FK to Job lives on the Job side (`job.event_id`), not on Event (Decision 37). This eliminates the write-back pattern and keeps events truly append-only.

**State machine**:

```
              route(agent_group_id)
RECEIVED ─────────────────────→ ROUTED ──→ (Job created with event_id referencing this Event)
  │
  │ suppress(reason)
  ↓
SUPPRESSED

  │ dedup(original_event_id)
  ↓
DEDUPLICATED
```

**Methods**: `route(agent_group_id)`, `suppress()`, `deduplicate(original_event_id)`

**Invariants**:
- `RECEIVED → ROUTED` on successful routing (agent_group_id set)
- `RECEIVED → SUPPRESSED` when filter rules explicitly suppress
- `RECEIVED → DEDUPLICATED` when fingerprint matches within dedup window (dedup_ref_id set)
- `ROUTED` events always have `agent_group_id` set
- Job references Event via `job.event_id` — Event does not reference Job
- Events are immutable — status/agent_group_id are write-once, no updates to raw_payload

**Fingerprinting**: Computed by source adapters from source-specific fields. Examples:
- Alertmanager: `sha256(alertname + labels.namespace + labels.pod)`
- Datadog: `sha256(monitor_id + alert_type)`
- Generic: `sha256(raw_payload)` or `None` (no dedup)

### EventSourceConfig

**File**: `domain/event_source_config.py`

Per-source webhook configuration. Links an external event source to an agent group with adapter settings. See Decision 35.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `name` | `str` | required | Display name (`"Prod Alertmanager"`) |
| `source` | `str` | required | Adapter name: `alertmanager`, `datadog`, `generic`, etc. |
| `agent_group_id` | `str` | required | Default routing target — FK → AgentGroup |
| `default_severity` | `EventSeverity \| None` | `None` | Fallback when source doesn't provide severity |
| `auth_token` | `str` | generated | Webhook authentication token (per-source) |
| `field_mappings` | `dict \| None` | `None` | Custom field extraction for generic webhooks |
| `dedup_window_seconds` | `int` | `300` | Fingerprint dedup window (default 5 min) |
| `enabled` | `bool` | `True` | |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

### LLMUsage

**File**: `domain/llm_usage.py`

Append-only telemetry record. One record per LLM API call (a single job may produce multiple records as the ReAct loop iterates).

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `job_id` | `str` | required | FK → Job |
| `session_id` | `str` | required | FK → Session (denormalized) |
| `agent_id` | `str` | required | FK → Agent |
| `agent_group_id` | `str` | required | FK → AgentGroup (denormalized) |
| `org_id` | `str` | required | FK → Organization (denormalized) |
| `model` | `str` | required | e.g., `gpt-4o`, `claude-sonnet-4-20250514` |
| `provider` | `str` | required | `openai`, `anthropic`, `azure-openai`, etc. |
| `input_tokens` | `int` | required | |
| `output_tokens` | `int` | required | |
| `total_tokens` | `int` | required | |
| `estimated_cost_usd` | `float` | `0.0` | Computed at write time from pricing table |
| `latency_ms` | `int \| None` | `None` | Round-trip time for the LLM call |
| `tool_calls` | `int` | `0` | Number of tool calls in this invocation |
| `created_at` | `datetime` | `utcnow()` | |

Denormalized FKs avoid joins in aggregation queries. Supports: cost per job/session/agent/group/org, token usage over time, model distribution, average latency.

### AuditEvent

**File**: `domain/audit_event.py`

A granular record of every action taken during job execution — tool calls, LLM decisions, approval requests. Append-only. Flows through the audit subsystem sinks (Decision 32). See Decision 42.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `job_id` | `str` | required | FK → Job |
| `agent_id` | `str` | required | FK → Agent |
| `session_id` | `str` | required | FK → Session (denormalized) |
| `org_id` | `str` | required | FK → Organization (denormalized) |
| `action` | `AuditAction` | required | Type of action recorded |
| `tool_name` | `str \| None` | `None` | Tool that was called (null for LLM decisions) |
| `input` | `dict \| None` | `None` | Tool input parameters or LLM prompt summary |
| `output` | `dict \| None` | `None` | Tool output or LLM response summary |
| `duration_ms` | `int \| None` | `None` | Execution time |
| `created_at` | `datetime` | `utcnow()` | |

**Enums**: `AuditAction`: `TOOL_CALL`, `TOOL_RESULT`, `LLM_DECISION`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`, `APPROVAL_DENIED`

**Invariants**:
- Append-only — no updates, no deletes
- Every Job (whether from Event or Session) emits AuditEvents — uniform audit trail regardless of trigger (Decision 38)
- Denormalized FKs avoid joins in compliance queries

### Message

**File**: `domain/message.py`

A structured entry in a session's timeline. Captures every significant interaction — human questions, agent findings, tool summaries, approval flows, and system events. Messages are the user-facing record of what happened; AuditEvents are the compliance-facing record of how it happened. See Decision 44.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `session_id` | `str` | required | FK → Session |
| `job_id` | `str \| None` | `None` | FK → Job. Null for human messages and system events without a job. |
| `author_type` | `AuthorType` | required | Who created this message |
| `author_id` | `str` | required | User identity (HUMAN), agent_id (AGENT), `"system"` (SYSTEM) |
| `message_type` | `MessageType` | required | Structured type for rendering and filtering |
| `content` | `str` | required | Primary text content |
| `metadata` | `dict` | `{}` | Structured payloads — tool output, approval details, scope info, etc. |
| `created_at` | `datetime` | `utcnow()` | |

**Enums**:
- `AuthorType`: `HUMAN`, `AGENT`, `SYSTEM`
- `MessageType`: `HUMAN_MESSAGE`, `AGENT_FINDING`, `AGENT_PROPOSAL`, `TOOL_SUMMARY`, `APPROVAL_REQUEST`, `APPROVAL_RESPONSE`, `SYSTEM_EVENT`, `STATUS_UPDATE`

**Message types**:

| Type | Author | When |
|:-----|:-------|:-----|
| `HUMAN_MESSAGE` | HUMAN | User asks a question, provides context, gives instructions |
| `AGENT_FINDING` | AGENT | Agent reports an observation or investigation result |
| `AGENT_PROPOSAL` | AGENT | Agent proposes an action that requires approval |
| `TOOL_SUMMARY` | AGENT | Summary of tool execution and key output |
| `APPROVAL_REQUEST` | SYSTEM | Formal approval request with action details in metadata |
| `APPROVAL_RESPONSE` | HUMAN | User approves or denies a proposed action |
| `SYSTEM_EVENT` | SYSTEM | Alert received, job created, agent assigned, state change |
| `STATUS_UPDATE` | SYSTEM | Incident or session state transitions |

**Invariants**:
- Messages are append-only — no updates, no deletes
- `session_id` is always set — every message belongs to a session
- `author_id` identifies the specific actor (enables "who said what" in multi-user sessions)
- `metadata` carries structured data that the UI renders specially (e.g., approval details, tool call parameters, scope information)

**Relationship to AuditEvent**: A single `TOOL_SUMMARY` message may correspond to multiple AuditEvents (agent ran 3 kubectl commands, message summarizes findings). Messages are for collaboration; AuditEvents are for compliance and forensics.

### Policy (Sprint D)

**File**: `domain/policy.py`

Execution rules scoped to organization, agent group, or capability. Governs what tools agents can use and whether approval is required. See Decision 41.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `scope` | `PolicyScope` | required | Where this policy applies |
| `scope_id` | `str \| None` | `None` | AgentGroup ID or capability name (null for org-wide) |
| `rules` | `list[PolicyRule]` | `[]` | Action-specific overrides |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**Enums**: `PolicyScope`: `ORG`, `GROUP`, `CAPABILITY`

**PolicyRule** (embedded value object): `{ action: str, requires_approval: bool, allowed: bool }`

**Evaluation order**: Tool-specific rule → Group policy → Org policy → AgentGroup `execution_mode` default. Most specific wins.

### Incident (enhanced from existing)

**File**: `domain/incident.py`

Groups related Events and Jobs by correlation. The existing Incident model (used by the incident bot) is enhanced with correlation_key and event associations for fleet use. See Decision 39. **Design now, build in Sprint D.**

Lifecycle: `OPEN → INVESTIGATING → MITIGATED → RESOLVED → CLOSED`.

| Field | Type | Default | Notes |
|:------|:-----|:--------|:------|
| `id` | `str` | `uuid4()` | Primary key |
| `org_id` | `str` | required | FK → Organization |
| `title` | `str` | required | Human-readable summary |
| `status` | `IncidentStatus` | `OPEN` | State machine |
| `severity` | `EventSeverity \| None` | `None` | Highest severity from associated events |
| `correlation_key` | `str \| None` | `None` | Groups events with matching correlation_key |
| `created_at` | `datetime` | `utcnow()` | |
| `updated_at` | `datetime` | `utcnow()` | |

**Enums**: `IncidentStatus`: `OPEN`, `INVESTIGATING`, `MITIGATED`, `RESOLVED`, `CLOSED`

**Relationships**:
- `Job.incident_id` (already exists) links jobs to incidents
- Events are grouped by matching `correlation_key` within a time window — logical grouping, not FK
- Not every event needs an incident — only when correlation logic identifies related work

---

## File Organization

Each entity gets its own file in `domain/`. This keeps files small and imports explicit.

```
domain/
├── incident.py              # Enhanced with correlation_key (Decision 39)
├── organization.py
├── agent_group.py           # + ExecutionMode enum (Decision 41)
├── agent.py
├── job.py                   # + event_id, required_capabilities, expanded JobType/JobStatus
├── session.py
├── channel_mapping.py
├── filter_rule.py
├── prompt_config.py
├── event.py                 # Event + EventType + EventSeverity + EventStatus
├── event_source_config.py   # EventSourceConfig
├── message.py               # Message + AuthorType + MessageType (Decision 44)
├── audit_event.py           # AuditEvent + AuditAction (Decision 42)
├── policy.py                # Policy + PolicyScope + PolicyRule (Sprint D, Decision 41)
└── llm_usage.py
```

---

## Incident Integration

`Job` links to `Incident` via `incident_id`. When a triage job's result warrants an incident, the service creates an `Incident` (using `IncidentService`) and sets `job.incident_id`. In Sprint D, `IncidentService` gains correlation-aware logic: events with matching `correlation_key` within a time window are grouped into the same incident, preventing duplicate investigations of the same outage (Decision 39).

The existing incident bot's incident lifecycle (`OPEN → INVESTIGATING → MITIGATED → RESOLVED → CLOSED`) is preserved and enhanced with event correlation.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. ClusterGroup → AgentGroup rename applied. session_id made required on Job. LLMUsage entity added. Surface-portable session fields added. |
| 2026-03-29 | Event architecture: Added Event entity (Decision 34) with two-layer model (raw envelope + normalized fields), EventSourceConfig entity (Decision 35). Updated entity relationship map and key relationships. |
| 2026-03-29 | Domain model refinement: Event made immutable — removed job_id, added type enum and correlation_key (Decision 37). Job gains event_id FK, required_capabilities, expanded JobType (7 types) and VERIFYING state (Decisions 37, 40, 43). AgentGroup gains execution_mode (Decision 41). Added AuditEvent (Decision 42), Policy (Decision 41), enhanced Incident with correlation_key (Decision 39). |
| 2026-03-29 | Session and UI elevation: Added Message entity with AuthorType and MessageType enums (Decision 44). Session description updated to "conversational workspace." Entity relationship map, key relationships, and file organization updated. |
