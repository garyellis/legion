# Architectural Decisions

Key decisions for the SRE agent fleet buildout and their rationale.

---

## 1. Slack Bolt Embedded in API

**Decision**: `api/main.py` hosts both FastAPI and Slack Bolt as a combined ASGI application.

**Context**: The SRE architecture requires the API to receive Slack events, dispatch jobs to agents over WebSocket, and post results back to Slack threads. These operations share the same database, services, and WebSocket connection pool.

**Options considered**:

| Option | Pros | Cons |
|:-------|:-----|:-----|
| **A: Combined process** | One DB pool, one set of services, no network hop for Slack→dispatch | Larger process, coupling |
| **B: Slack as API client** | Simpler to build incrementally, independent scaling | Duplicated DB connections, extra latency, sync complexity |

**Choice**: Option A. The Slack Bolt `AsyncApp` is already ASGI-compatible. FastAPI can mount it as a sub-application. The shared services and database connection avoid duplication. The existing `legion-slack` entry point is preserved for simple single-node deployments that don't need the fleet.

---

## 2. Domain Entities in `domain/`, Not in Services

**Decision**: Fleet entities (Organization, ClusterGroup, Agent, Job, etc.) are Pydantic models in `domain/`, with ORM rows in `services/`.

**Context**: These entities are referenced by multiple surfaces (CLI configures them, API serves them, Slack triggers through them, agents execute them). They also cross core boundaries (a Job references Slack channels, cluster infrastructure, and AI execution).

**Rationale**: This follows the existing pattern. `Incident` is in `domain/` because it spans multiple concerns. `IncidentRow` (ORM) is in `services/repository.py`. The domain stays persistence-free; the service layer handles mapping.

---

## 3. One Repository Per Aggregate, Not Per Entity

**Decision**: Group simple CRUD entities into shared repositories rather than creating one ABC per entity.

**Context**: The fleet has 7+ entities. Creating 7 ABCs, 7 InMemory impls, and 7 SQLite impls would be tedious and add little value for entities with trivial query patterns (Organization, ChannelMapping, FilterRule, PromptConfig).

**Approach**:
- **`JobRepository`** — dedicated, because Job has complex queries (list pending by cluster group, reassign, status transitions)
- **`FleetRepository`** — combined repository for Organization, ClusterGroup, Agent, ChannelMapping, FilterRule, PromptConfig (simple CRUD)

If a combined repository becomes unwieldy, split it. Start simple.

---

## 4. CLI Always Goes Through the API

**Decision**: The CLI is an API client from day one. It never talks to the database directly.

**Context**: The CLI needs to configure fleet entities. It could either instantiate services directly (like `legion-slack` does today) or call the API over HTTP.

**Options considered**:

| Option | Pros | Cons |
|:-------|:-----|:-----|
| **A: Direct DB access first, API client later** | Faster to build initially, no API dependency | Bypasses API validation/business logic, split-brain risk, two code paths to maintain |
| **B: API client only** | Single writer to the database, consistent validation, no split-brain | Requires API to be running, Phase 2 must precede Phase 3 |

**Choice**: Option B. The API is the single writer to the database. This enforces a clear data access boundary — all writes flow through the same validation and business logic regardless of whether they originate from Slack, the CLI, or a future UI. Direct database access from the CLI would bypass API-layer validation and create a second code path that could diverge. The dependency on a running API is a feature, not a cost: if the API is down, operators should know about it, not silently work around it.

---

## 5. Interactive Chat via Dedicated Channels and Sessions

**Decision**: Users chat with agents through dedicated Slack channels. Each channel maps to a cluster group. Conversations are tracked as sessions that pin to a specific agent for context continuity.

**Context**: Beyond automated triage, operators need to interactively query infrastructure — "what's the replication lag on the prod DB?", "show me the last 50 lines of the payment pod logs", etc. This should feel like chatting with an engineer who has access to the cluster.

**Options considered**:

| Option | Pros | Cons |
|:-------|:-----|:-----|
| **A: One-shot query jobs** | Simple, no new concepts | No conversational context, agent can't refer to previous answers |
| **B: Session-based conversations** | Agent retains context across turns, natural chat UX | New `Session` entity, agent affinity routing |

**Choice**: Option B. A `Session` groups related messages into a conversation pinned to one agent. When a message arrives in a chat channel, the dispatcher checks for an active session in that Slack thread. If one exists, it routes to the same agent. If not, it creates a new session and assigns an idle agent.

**Channel types**: `ChannelMapping` gains a `mode` field — `alert` (existing: filter rules evaluate messages, triage jobs created) or `chat` (new: every message becomes a query job routed through sessions). This is a single field, not a new entity.

**Surface portability**: Sessions are API-level concepts (domain + service). Slack is one surface; an admin UI/dashboard can offer the same chat experience by calling the same API endpoints. The session, job dispatch, and streaming all work identically regardless of surface.

---

## 6. Agent Process as a Surface

**Decision**: The data-plane agent (`legion-agent`) is classified as a surface, not a new layer.

**Context**: The agent process connects to the API, receives job payloads, executes them, and sends results back. It's tempting to think of it as something new.

**Rationale**: It follows the exact same pattern as other surfaces:
- Parses input (job payloads from WebSocket)
- Calls logic (agents/ ReAct loop → core/ tools)
- Formats output (structured results back over WebSocket)

It imports from `agents/`, `services/`, `domain/`, `core/`, and `plumbing/`. Same dependency rules. Calling it a surface keeps the mental model simple.

---

## 7. Single LangGraph Agent for Chat and Event Processing

**Decision**: One LangGraph `StateGraph` handles both interactive chat and one-shot event processing. The graph is the same; the entry configuration differs.

**Context**: Agents handle two workloads — multi-turn chat sessions (user asking questions interactively) and single-turn triage jobs (alert routed by the control plane). These could be separate graphs or a single parameterized graph.

**Options considered**:

| Option | Pros | Cons |
|:-------|:-----|:-----|
| **A: Separate graphs** | Each optimized for its workload | Duplicated tool wiring, two ReAct implementations to maintain |
| **B: Single graph, parameterized** | One set of tools, one loop, consistent behavior | Slightly more complex entry configuration |

**Choice**: Option B. The ReAct loop is identical — `observe → plan → act → respond` — using the same `core/` tools. What differs is configuration at entry:

| | Chat | Event processing |
|:--|:-----|:-----------------|
| **Checkpointer** | Loads prior conversation (keyed by `session.id`) | Starts fresh (keyed by `job.id`) |
| **System prompt** | Conversational persona from `PromptConfig` | Alert-analysis prompt from `PromptConfig` |
| **Streaming** | Required (tokens back to Slack/UI) | Progress updates (optional) |
| **Turns** | Multi-turn, session-pinned agent | Single-turn, stateless |

The agent process receives a job, checks for `session_id` — if set, loads the checkpoint; if not, starts clean. The graph doesn't know or care about the origin.

**LangGraph specifics**:
- `StateGraph` + `ToolNode` for the ReAct loop
- Built-in checkpointer interface adapts to our DB-backed persistence (via `services/`)
- Interrupt/breakpoint mechanism maps to `tool_interceptor` (human-in-the-loop for destructive ops)
- `langchain-core` and `langchain-openai` are already dependencies

**File structure**:
```
agents/
├── graph.py          # Single StateGraph — tools, ReAct loop
├── checkpointer.py   # DB-backed persistence adapter (via services layer)
├── context.py        # Token budget, rolling compaction
└── evaluator.py      # Factual grounding check
```

LangGraph stays in `agents/` only. It does not leak into `services/`, `domain/`, or `core/`.

---

## 8. Watchdog Agents — External Observers

**Decision**: Watchdog agents run outside clusters and monitor externally visible signals. They use the same agent graph and control plane but carry a different tool set and can self-generate triage jobs.

**Context**: An agent running inside a cluster can't report "the whole cluster is down." External observation — endpoint health, DNS, TLS certs, synthetic transactions — requires a different deployment posture.

**Rationale**: A watchdog is just another agent registered to a cluster group. The control plane doesn't distinguish inside vs. outside — it dispatches jobs and receives results. What differs:

- **Tool set**: HTTP probes, DNS resolution, TLS inspection, port reachability, synthetic transactions — no kubectl, no cluster credentials
- **Job flow**: Watchdogs can self-generate jobs. They observe, detect degradation, and create `TRIAGE` jobs back through the API. Inside agents wait for dispatch; watchdogs push.
- **Deployment**: Runs anywhere with network access to the monitored endpoints. Does not need cluster credentials.

**Self-generated jobs**: A watchdog calls the API's job creation endpoint when it detects an anomaly. This is the same endpoint the Slack listener and filter service use. The control plane then dispatches the resulting triage job to an inside agent that has the credentials to investigate further.

**Use cases**:
- Endpoint health probes on a schedule
- Certificate expiry warnings (N days out)
- Synthetic transactions against public APIs
- Cross-cluster comparison ("prod-us vs prod-eu response times")
- "Cluster unreachable" detection — the one thing an inside agent can never report

---

## 9. Inter-Agent Queries with Security Boundaries

**Decision**: Agents can query other agents through the control plane. Cross-agent queries are governed by an allowlist policy that restricts which cluster groups can communicate.

**Context**: An agent triaging an issue in one cluster may need information from another — "what's the replication lag on prod?" or "did a deploy just happen in staging?" — without having credentials for that cluster. The natural mechanism is for the requesting agent to create a job targeting the other cluster group, routed through the control plane. But unrestricted cross-agent queries create security risks: a dev agent should not be able to interrogate prod infrastructure.

**Mechanism**: Inter-agent query is a tool in `core/fleet/` that creates a `QUERY` job via the API, targeting a specified cluster group. The control plane dispatches it to an idle agent in that group. The result returns through the normal job completion flow. From the requesting agent's perspective, it's a tool call that blocks until the result is ready.

**Security boundaries**: A `QueryPolicy` (part of the fleet configuration) defines an allowlist of permitted cluster group pairs:

```python
# domain/query_policy.py
class QueryPolicy(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    org_id: str
    source_cluster_group_id: str      # Who is asking
    target_cluster_group_id: str      # Who is being asked
    allowed: bool = True              # Explicit allow (deny by default)
```

The `DispatchService` enforces the policy at job creation time. If no policy exists for the `(source, target)` pair, the query is denied. This is **deny by default** — every cross-agent path must be explicitly opened.

**Example policies**:

| Source | Target | Allowed | Rationale |
|:-------|:-------|:--------|:----------|
| prod-aks | prod-db | Yes | Prod agents can query each other |
| staging-aks | staging-db | Yes | Staging agents can query each other |
| watchdog | prod-aks | Yes | Watchdog can trigger prod investigation |
| dev-aks | prod-aks | **No** | Dev must not access prod |
| prod-aks | dev-aks | **No** | Prod has no reason to query dev |

**Cycle prevention**: Jobs carry a `depth` field (default 0). Each inter-agent query increments depth. The API rejects jobs beyond a configurable max depth (default 3). This prevents A → B → A loops and runaway delegation chains.

**Audit**: Every inter-agent query is a normal `Job` in the database — fully tracked, with source agent, target cluster group, payload, and result. The query policy enforcement is logged. This gives a complete audit trail of which agents asked what, of whom, and whether it was allowed.

---

## 10. PostgreSQL for Production, SQLite for Dev

**Decision**: The control plane uses PostgreSQL in production. SQLite remains the default for local development and testing.

**Context**: The fleet API needs concurrent access from multiple WebSocket connections, Slack event handlers, and CRUD routes. SQLite's write lock becomes a bottleneck.

**Rationale**: The `plumbing/database.py` engine factory already handles both dialects. `DatabaseConfig.url` defaults to `sqlite:///legion.db` and switches to PostgreSQL via `DATABASE_URL=postgresql+psycopg://...`. The `psycopg[binary]` optional dependency is already in `pyproject.toml`. Repository contract tests run against in-memory SQLite, so PostgreSQL-specific issues are caught by integration tests in CI.

---

## 11. WebSocket for Agent Communication, Database for Durability

**Decision**: WebSocket is the delivery mechanism. The database is the durability layer.

**Context**: Agents connect to the API via WebSocket. Jobs could be dispatched purely in-memory (fast) or persisted first (durable).

**Rationale**: Jobs are always written to the database before dispatch. If a WebSocket drops:
- The job stays `assigned` in the DB
- A heartbeat timeout marks the agent `offline`
- The job transitions to `pending` and gets reassigned

This means no work is lost on disconnect. The WebSocket is just a push notification channel. Even at 1000 clusters, job volume (dozens per hour at peak) is well within what a relational database handles.

---

## 12. Knowledge Layer Starts with Git + Markdown

**Decision**: The knowledge base is a Git repository of markdown files. No vector database initially.

**Context**: Agents need runbooks, stack manifests, known alert patterns, and post-incident reports to do effective triage.

**Rationale**: Git + markdown gives version control, human readability, PR-based review, and zero infrastructure. Agents clone on boot, pull at job start. The repo URL is part of the cluster group config, so different environments can use different knowledge bases.

A vector index can be layered on later for semantic search when the knowledge base grows large enough. Markdown stays the source of truth; embeddings are a derived index.

---

## 12. Filter Rules Evaluated Server-Side

**Decision**: Filter rules are evaluated by the API when a Slack message arrives, not by agents.

**Context**: When a message arrives in a mapped alert channel, something must decide whether it triggers a triage job.

**Rationale**: The API has the filter rules in its database. Evaluating them server-side means:
- No config sync to agents
- Filter changes take effect immediately
- Agents stay stateless — they only receive jobs, not raw messages
- The `FilterService` is a pure function: `(message, rules) → should_triage`

---

## 13. Preserve `legion-slack` for Simple Deployments

**Decision**: The standalone `legion-slack` entry point is kept alongside the new `legion-api` combined process.

**Context**: Not every deployment needs the full fleet. A single-node Slack bot with SQLite is a valid use case.

**Rationale**: `legion-slack` works today with no API, no PostgreSQL, no WebSocket. Removing it would force every user into the full fleet architecture. Instead:
- `legion-slack` — standalone incident bot (SQLite, no fleet)
- `legion-api` — combined API + Slack + fleet (PostgreSQL, WebSocket, agents)

The same services, repositories, and domain models power both. The difference is the wiring in `main.py`.
