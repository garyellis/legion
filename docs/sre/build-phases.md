# Build Phases

Ordered implementation plan. Each phase is independently testable and demoable. The existing incident bot keeps working throughout.

---

## Phase 1: Domain + Services

**Goal**: All fleet business logic exists, tested, no surfaces yet.

**Testable with**: `uv run pytest`

### Deliverables

1. **Domain entities** in `domain/`:
   - `organization.py`, `cluster_group.py`, `agent.py`, `channel_mapping.py`, `filter_rule.py`, `prompt_config.py`, `session.py`, `job.py`
   - Pure Pydantic models, state transitions on `Job`, `Agent`, and `Session`
   - `ChannelMapping` includes `ChannelMode` enum (`alert` / `chat`)

2. **Repositories** in `services/`:
   - `job_repository.py` — ABC + InMemory + SQLite for `Job`
   - `session_repository.py` — ABC + InMemory + SQLite for `Session`
   - `fleet_repository.py` — ABC + InMemory + SQLite for `Organization`, `ClusterGroup`, `Agent`, `ChannelMapping`, `FilterRule`, `PromptConfig`
   - ORM rows inheriting from `plumbing.database.Base`

3. **Services** in `services/`:
   - `job_service.py` — create job, assign to agent, mark complete/failed, reassign on disconnect
   - `dispatch_service.py` — resolve channel → cluster group, pick idle agent, queue if none available; for chat channels, route through sessions with agent affinity
   - `session_service.py` — create/close sessions, get-or-create by thread, enforce agent pinning
   - `filter_service.py` — evaluate filter rules against message text (alert channels only)

4. **Tests**:
   - Domain unit tests (state transitions, validation)
   - Repository contract tests (parameterized: memory + sqlite)
   - Service tests with in-memory repos and stub callbacks
   - Dependency direction test updated for new files

### What to watch for

- `Job` status transitions: ensure `pending → assigned → running → completed` and `assigned → pending` (reassign) are the only valid paths
- `Agent` state: `offline → idle` on connect, `idle → busy` on dispatch, `busy → idle` on complete, `* → offline` on disconnect
- Filter rule evaluation order: higher priority first, short-circuit on first match

---

## Phase 2: API Surface (CRUD + WebSocket)

**Goal**: Fleet is configurable and agents can connect. No Slack yet.

**Testable with**: `curl`, `httpie`, `websocat`

### Deliverables

1. **API bootstrap** in `api/`:
   - `api/main.py` — FastAPI app, database engine creation, DI wiring
   - `legion-api` entry point in `pyproject.toml`

2. **CRUD routes** in `api/routes/`:
   - `organizations.py` — create, list, get
   - `cluster_groups.py` — create, list by org, get
   - `channel_mappings.py` — create, list by org, get, delete
   - `filter_rules.py` — create, list by channel, get, delete
   - `prompt_configs.py` — create/update by cluster group, get
   - `jobs.py` — list by cluster group, get, get status
   - `sessions.py` — create, list by cluster group, get, send message (creates query job within session)

3. **WebSocket handler** in `api/`:
   - `websocket.py` — `/ws/agents/{agent_id}` endpoint
   - Agent registration on connect, state tracking, heartbeat via ping/pong
   - Job dispatch over WebSocket, result receipt

4. **Config**:
   - `api/config.py` — `APIConfig` extending `LegionConfig` (host, port, etc.)

5. **Tests**:
   - FastAPI TestClient for CRUD routes
   - WebSocket connection/dispatch integration test

### What to watch for

- WebSocket lifecycle: clean disconnect handling, heartbeat timeout → offline
- Job queue drain: when an agent completes a job, check for pending jobs in its cluster group
- Auth is out of scope for Phase 2 — add API key middleware later

---

## Phase 3: CLI Admin Commands

**Goal**: Operators can configure the fleet from the terminal.

**Testable with**: `uv run legion-cli fleet ...`

### Deliverables

1. **CLI commands** in `cli/commands/fleet.py`:
   ```
   legion-cli fleet cluster register dev-aks
   legion-cli fleet cluster list
   legion-cli fleet channel map C12345 --cluster dev-aks
   legion-cli fleet filter add C12345 --pattern "CRITICAL|ERROR" --action triage
   legion-cli fleet prompt set dev-aks --system-prompt "You are a K8s expert" --stack "App → Redis → PG"
   legion-cli fleet jobs list --cluster prod-aks
   legion-cli fleet agents status
   ```

2. **CLI views** in `cli/views/fleet.py`:
   - Rich tables for cluster groups, agents, jobs, channel mappings

3. **API client** in `cli/fleet_client.py`:
   - HTTP client targeting the API CRUD routes from Phase 2
   - The CLI never talks to the database directly — the API is the single writer

### What to watch for

- The CLI depends on a running API. Phase 2 must be complete (or built alongside Phase 3).
- Use existing `cli/registry.py` pattern for command registration.
- Keep the HTTP client thin — it maps CLI args to API calls and formats responses. No business logic in the CLI.

---

## Phase 4: Slack Integration into API

**Goal**: Slack events trigger job dispatch. Results post back to threads.

**Testable with**: Slack workspace + running API

### Deliverables

1. **Slack Bolt as ASGI sub-app** in `api/main.py`:
   - Mount Slack Bolt alongside FastAPI routes
   - Shared engine, services, and repositories

2. **Event listeners** in `slack/listeners/` (new directory):
   - `alert_listener.py` — listen for messages in mapped alert channels (`mode=alert`), evaluate filter rules, create triage jobs via `DispatchService`
   - `chat_listener.py` — listen for messages in mapped chat channels (`mode=chat`), get-or-create session by thread, create query jobs with agent affinity via `SessionService` + `DispatchService`
   - `mention_listener.py` — `@legion` mentions create query jobs

3. **Result posting**:
   - When `JobService` completes a job (via callback), post structured results to `job.slack_channel_id` / `job.slack_thread_ts`
   - Use existing `core/slack/client.py` for posting

4. **Existing incident commands preserved**:
   - `/incident`, `/resolve` continue working via existing handlers
   - They use the same `IncidentService` and database

5. **Updated entry points** in `pyproject.toml`:
   - `legion-api` runs the combined API + Slack process (fleet mode)
   - `legion-slack` still works standalone (simple mode, no fleet)

### What to watch for

- Slack Bolt and FastAPI share an async event loop. Use `AsyncApp` (already in use).
- The result posting callback must handle rate limits and thread formatting.
- Chat channels: every message in the channel becomes a query job. The `chat_listener` uses Slack threads as session boundaries — same thread = same session = same agent.
- Streaming: for chat channels, `job_progress` WebSocket messages should stream tokens back to the Slack thread for a responsive UX.
- Keep `legion-slack` working as-is for users who don't need the fleet.

---

## Phase 5: Data-Plane Agent

**Goal**: Agents run in target clusters, connect to the API, execute jobs.

**Testable with**: Run agent locally, point at API, dispatch test jobs

### Deliverables

1. **Agent process** — new entry point `legion-agent`:
   - `agent_runner/main.py` (or similar surface directory)
   - WebSocket client connecting to `ws://<api>/ws/agents/{agent_id}`
   - Job receive → execute → result send loop

2. **ReAct loop infrastructure** in `agents/`:
   - `graph.py` — agent graph with tool dispatch
   - `evaluator.py` — factual grounding check
   - `tool_interceptor.py` — destructive operation gates
   - `context.py` — token budget, rolling compaction

3. **Local tools** in `core/`:
   - `core/kubernetes/` — kubectl wrapper (pod status, logs, describe)
   - `core/database/` — connection check, replication lag query
   - `core/network/` — already exists (DNS, SSH), extend as needed
   - Tools decorated for agent discovery

4. **Knowledge layer**:
   - Git clone of knowledge repo on boot
   - Git pull at job start
   - File-path lookup + keyword search (no vector DB yet)

5. **Config**:
   - `AgentRunnerConfig` — API URL, agent ID, cluster group, knowledge repo URL

### What to watch for

- The agent is a surface: it parses input (job payloads), calls logic (agents/ ReAct), formats output (structured results). Same dependency rules.
- WebSocket reconnection with exponential backoff.
- Credential isolation: kubeconfig, SSH keys, DB passwords stay local to the agent. Never sent to the API.
- Streaming: agents send `job_progress` messages for real-time Slack updates.

---

## Phase 6: Watchdog Agents

**Goal**: External observers that monitor clusters from outside and self-generate triage jobs.

**Testable with**: Run watchdog agent locally, point at API, watch it create jobs when probes fail

### Deliverables

1. **Watchdog tools** in `core/`:
   - `core/http/` — endpoint health probes, response time measurement
   - `core/tls/` — certificate inspection, expiry checks
   - `core/dns/` — resolution checks, propagation validation
   - `core/synthetic/` — synthetic transaction runner

2. **Self-generated jobs**:
   - Watchdog calls the API's job creation endpoint when it detects anomalies
   - Created jobs are `TRIAGE` type, dispatched to inside agents with cluster credentials

3. **Scheduling**:
   - Watchdog runs probe loops on configurable intervals
   - Anomaly detection triggers immediate job creation (not scheduled polling)

4. **Config**:
   - `WatchdogConfig` — probe targets, intervals, thresholds, API URL

### What to watch for

- A watchdog detecting "cluster unreachable" should create a triage job, but the inside agent for that cluster may be offline. The control plane queues the job until an agent reconnects or escalates.
- Watchdogs should not flood the API with jobs on a sustained outage. Debounce / dedup logic in the watchdog or the API's filter service.
- Watchdog agents use the same LangGraph graph as inside agents — different tools, same loop.

---

## Phase Summary

| Phase | What You Get | How You Test |
|:------|:-------------|:-------------|
| 1 | Fleet business logic | `pytest` |
| 2 | Configurable fleet API | `curl` / `httpie` |
| 3 | Operator CLI | `legion-cli fleet ...` |
| 4 | Slack-triggered dispatch + chat | Slack workspace |
| 5 | Running agents in clusters | Agent process + API |
| 6 | External watchdog monitoring | Watchdog process + API |

Each phase builds on the previous one. No phase requires the next one to be useful.
