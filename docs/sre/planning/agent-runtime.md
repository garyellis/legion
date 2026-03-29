# Agent Runtime

> The data-plane agent process, AI runtime infrastructure, knowledge layer, tools, and guardrails.

---

## 1. Agent Process Architecture

The agent process (`legion-agent`) is a **surface** — it follows the same pattern as CLI and Slack:

- **Parses input**: Job payloads from WebSocket
- **Calls logic**: `agents/` ReAct loop → `core/` tools
- **Formats output**: Structured results back over WebSocket

It imports from `agents/`, `services/`, `domain/`, `core/`, and `plumbing/`. Same dependency rules as every other surface.

### Entry Point

```
agent_runner/
├── main.py          # legion-agent entry point
├── ws_client.py     # WebSocket client with reconnection
└── config.py        # AgentRunnerConfig
```

### Job Execution Loop

```
Connect to API via WebSocket
  → Authenticate with API key
  → Mark IDLE, receive pending jobs
  → For each job:
      1. Receive job_dispatch (payload, session_id, prompt_config)
      2. Send job_started
      3. Load session checkpoint (if session has history)
      4. Execute ReAct loop with local tools
      5. Stream job_progress messages for real-time updates
      6. Send job_result or job_failed
      7. Send llm_usage records
      8. Wait for next job
```

### Resilience

- **Reconnection**: Exponential backoff with jitter, capped at 5 minutes
- **Logging**: Log first disconnect, decrease retry log frequency, log successful reconnection
- **Job safety**: Jobs assigned to a disconnected agent: heartbeat timeout → agent offline → job reverts to PENDING → reassigned by control plane
- **Credential isolation**: kubeconfig, SSH keys, DB passwords stay local. Never sent to the API. Only structured results flow back.

---

## 2. AI Runtime (`agents/`)

### File Structure

```
agents/
├── graph.py          # Single StateGraph — tools, ReAct loop
├── checkpointer.py   # DB-backed persistence adapter (via services layer)
├── context.py        # Token budget, rolling compaction
├── evaluator.py      # Factual grounding check
├── tool_interceptor.py  # Human-in-the-loop for destructive ops
├── config.py         # AgentConfig (model/provider settings)
├── exceptions.py     # Agent-layer exception types
├── personas/         # Graph agent configs (prompt templates, tool lists)
└── chains/           # Simple LLM pipelines (no ReAct graph)
    ├── scribe.py     # AI-generated incident updates
    └── post_mortem.py  # Post-incident report generation
```

### Single LangGraph Graph for Chat and Events

One `StateGraph` handles both interactive chat and one-shot event processing. The ReAct loop is identical — `observe → plan → act → respond` — using the same `core/` tools. What differs is entry configuration:

| | Chat | Event Processing |
|:--|:-----|:-----------------|
| **Checkpointer** | Loads prior conversation (keyed by `session.id`) | Starts fresh (keyed by `job.id`) |
| **System prompt** | Conversational persona from `PromptConfig` | Alert-analysis prompt from `PromptConfig` |
| **Streaming** | Required (tokens back to Slack/UI) | Progress updates (optional) |
| **Turns** | Multi-turn, session-pinned agent | Single-turn, stateless |

The agent process receives a job, checks for `session_id` — if the session has history, loads the checkpoint; if not, starts clean. The graph doesn't know or care about the origin.

### LangGraph Components

- **`StateGraph` + `ToolNode`** for the ReAct loop
- **Built-in checkpointer interface** adapts to DB-backed persistence via `services/`
- **Interrupt/breakpoint mechanism** maps to `tool_interceptor` for human-in-the-loop
- **`langchain-core` and `langchain-openai`** are already dependencies

### Agent Parallelism

Each agent process handles **one job at a time**. The control plane handles scheduling.

- Agent may perform asynchronous internal operations within that one job
- Agent may spawn child tasks/subagents as part of the job
- Control plane schedules at the job level, not the thread level
- Horizontal scaling: add more agents to an agent group
- Single-job ownership gives clear diagnostics, predictable token budget, and operational well-being

---

## 3. Tools

### Architecture: Plugin System + Adapter Pattern (Decisions 22, 27)

Core tools are the first plugins. External tools use the same mechanism. The `@tool` decorator in `plumbing/plugins.py` annotates metadata. Discovery via Python entry points.

```
plumbing/plugins.py              <- @tool decorator (metadata only, no AI imports)
  ↑ used by
core/kubernetes/pods.py          <- @tool decorated function (plain Python)
core/database/queries.py         <- @tool decorated function
third_party_package/             <- same @tool, same entry points
  ↑ discovered by
agents/tools.py                  <- entry point discovery → LangChain StructuredTool
  ↑ also consumed by
slack/commands/, cli/commands/   <- direct import from core/
```

**Why**: The core function IS the tool contract. Type hints define the parameter schema. Docstrings define the description. The `@tool` decorator adds category and read_only classification. Everything else is an adapter for a specific consumer.

### Tool Plugin Example

```python
# core/kubernetes/pods.py — plain Python, @tool from plumbing
from legion.plumbing.plugins import tool

@tool(category="kubernetes", read_only=True)
def get_pod_status(namespace: str, pod_name: str) -> str:
    """Get the current status of a Kubernetes pod including
    restart count, conditions, and container states."""
    # pure infrastructure code using kubernetes client
    ...

@tool(category="kubernetes", read_only=True)
def get_pod_logs(namespace: str, pod_name: str, tail: int = 100) -> str:
    """Get recent logs from a Kubernetes pod."""
    ...

# core/kubernetes/__init__.py — export for entry point
from legion.plumbing.plugins import ToolSet
tools = ToolSet.collect_from_module("legion.core.kubernetes")

# pyproject.toml — register as entry point
# [project.entry-points."legion.tools"]
# kubernetes = "legion.core.kubernetes:tools"

# agents/tools.py — discovers ALL plugins at startup
from legion.plumbing.plugins import discover_tools
from langchain_core.tools import StructuredTool

def load_agent_tools() -> list[StructuredTool]:
    """Discover all installed tool plugins and adapt for LangChain."""
    plugins = discover_tools()  # reads legion.tools entry points
    return [StructuredTool.from_function(t.func) for t in plugins]
```

**Third-party plugin** — identical mechanism:
```
pip install legion-datadog-tools
→ registers entry point: legion.tools/datadog
→ agents discover it on next startup
→ legion-cli plugins list shows it
```

### Planned Core Tools

| Module | Tools | Used By |
|:-------|:------|:--------|
| `core/kubernetes/` | Pod status, logs, describe, events | Inside agents |
| `core/database/` | Connection check, replication lag, slow queries | Inside agents |
| `core/network/` | DNS, SSH, port check (existing, extend) | Both |
| `core/http/` | Endpoint probes, response time | Watchdog agents |
| `core/tls/` | Certificate inspection, expiry | Watchdog agents |
| `core/synthetic/` | Synthetic transaction runner | Watchdog agents |

### Tool Classification

| Category | Behavior | Examples |
|:---------|:---------|:---------|
| **Read-only** | Execute freely, no approval needed | kubectl get, psql SELECT, DNS lookup |
| **Write/mutate** | Requires human approval via `tool_interceptor` | kubectl delete pod, scale deployment, run SQL DDL |

### Tool Interception and Guardrails

Destructive operations must be gated. The approval flow:

1. Agent requests approval for destructive tool call
2. Control plane receives request
3. Slack message sent to operator: "Agent wants to restart pod X. Approve/Deny?"
4. Operator responds
5. Agent proceeds or aborts

**Timeout**: If no response within configurable window, operation is denied by default.

---

## 4. Knowledge Layer

### Git + Markdown First

The knowledge base is a Git repository of markdown files. No vector database initially.

**Why**:
- Version control and human readability
- PR-based review for quality
- Zero additional infrastructure
- Agents clone on boot, pull at job start — cheap and consistent

The repo URL is part of the agent group config, delivered in job payloads. Different agent groups can use different knowledge bases.

### Repository Structure

```
knowledge/
├── runbooks/
│   ├── redis-connection-timeout.md
│   └── postgres-replication-lag.md
├── stack-manifests/
│   ├── dev-aks.md
│   └── prod-aks.md
├── pir/
│   └── 2026-03-10-payment-api-outage.md
└── alerts/
    ├── known-patterns.md
    └── false-positives.md
```

### Learning Loop

After resolved incidents, the agent or reviewing human writes markdown back to the repo. Over time, the knowledge base grows organically from real operational experience.

**Agents propose, humans approve**: Agents create a branch + PR via the control plane. Humans review and merge. Quality stays high, audit trail is automatic.

### Vector Index (Future)

When the knowledge base grows large enough that file-path and keyword search aren't sufficient, a vector index can be layered on for semantic retrieval. Markdown stays the source of truth; embeddings are a derived index.

---

## 5. Workflow Design

### MVP Workflows

| Workflow | Type | Description |
|:---------|:-----|:------------|
| **Alert triage** | Read-only investigation | Receive alert, investigate cluster state, summarize findings, recommend actions |
| **Interactive query** | Conversational | Answer operator questions about cluster/infrastructure state |

### Future Workflows

| Workflow | Type | Description |
|:---------|:-----|:------------|
| **Runbook execution** | Write (with approval) | Execute runbook steps, gated by tool interceptor |
| **Diagnostic collection** | Read-only | Gather logs, metrics, state for incident response |
| **Post-incident analysis** | Read-only | Analyze incident timeline, generate report |
| **Delegated code fixes** | Write (with approval) | Delegate to agent CLI plugin (OpenCode, Aider, etc.), receive PR |

### Persona and Sub-Agent Strategy

Start simple: **one persona per agent group** via `PromptConfig`. The system prompt, stack manifest, and persona in PromptConfig define what the agent knows and how it behaves.

Sub-agent delegation (e.g., "this looks like a DB issue → invoke DB expert") is a later optimization. The top-level ReAct loop with the right prompt and tools is sufficient for MVP.

### Agent CLI Plugins (Decision 28)

Legion can delegate to specialized AI agent CLIs. These are tool plugins — same `@tool` decorator, same entry points. Classified as write/mutate, gated by tool interceptor.

| Agent CLI | Strength | Use Case |
|:----------|:---------|:---------|
| OpenCode | OSS, local-first | Fix deployment manifests, Helm values |
| Aider | Git-native, diff-focused | Targeted code edits with PR output |
| Claude Code | Most capable, tool use | Complex multi-file changes, runbook writing |
| Custom scripts | Team-specific | Automated remediation procedures |

**Flow**: Legion agent triages → identifies code fix needed → delegates to coding agent plugin → coding agent creates branch + PR → result posted to operator.

**Security**: See [Threat Model](./threat-model.md) Section 5. Workspace isolation, PR-only output, human approval, hard timeout, full audit trail.

### What Makes This System Valuable (vs. a General Coding Agent)

- Agent orchestration platform — delegates to specialized agents, not just tools
- Infrastructure credentials scoped to the cluster
- Organization-specific runbooks and stack context
- Fleet-wide visibility through the control plane
- Security boundaries enforced by policy
- Session continuity for multi-turn investigation
- Streaming results for responsive UX

---

## 6. Agent Local API

The agent process exposes a minimal local HTTP endpoint for:

- **Health check**: Kubernetes liveness/readiness probes
- **Status reporting**:
  - Git connectivity (knowledge repo reachable?)
  - Model connectivity (LLM endpoint healthy?)
  - Tools activated and available
  - Custom prompts loaded
  - Configured targets (names only, never secret values)

This endpoint is read-only. No management operations exposed.

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Consolidated from build-phases.md Phase 5, decisions.md (11, 12, 13, 16), 2026-03-20-planning.md Phases 5-7. |
| 2026-03-29 | Updated tool section: Registry + Adapter pattern (Decision 22). Core functions stay framework-free, adapter in agents/tools.py. |
| 2026-03-29 | Tools section updated for plugin system (Decision 27). Core tools are first plugins. @tool decorator in plumbing/plugins.py. Entry point discovery. |
| 2026-03-29 | Added Agent CLI Plugins section (Decision 28). Delegated coding agents as tool plugins. |
