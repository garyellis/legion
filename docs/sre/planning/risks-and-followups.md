# Risks and Follow-Ups

> Tracked risks, open questions, and follow-up items identified during architecture review. Items are resolved in place — update status, don't delete.

---

## Risk Register

### R1: LangGraph Checkpointer Integration (Sprint B2) — HIGH

**Risk**: LangGraph's checkpointer assumes it owns the persistence layer. Mapping its checkpoint keys to Legion's session/job model (chat sessions load history, triage jobs start fresh) may require wrapping or forking the checkpointer in ways that break on LangGraph upgrades.

**Why it's hard**: This isn't a "write code fast" problem — it's a compatibility mapping problem. LangGraph's internals need to defer to Legion's service layer while maintaining session-aware keying.

**Mitigation**:
- Budget 1-2 extra days in B2 specifically for this
- Spike the checkpointer adapter early in B2 before building the full ReAct loop around it
- If the built-in checkpointer interface doesn't fit, consider a thin wrapper that translates Legion session/job IDs to LangGraph checkpoint keys
- Pin LangGraph version and test upgrades explicitly

**Status**: OPEN
**Sprint**: B2
**Decision refs**: 12

---

### R2: Single-Worker Scaling (Post-B2) — MEDIUM

**Risk**: `ConnectionManager` is in-process. A single FastAPI worker handles all WebSocket connections, REST requests, dedup queries, and audit event flushing. Under load (many agents streaming `command_progress` concurrently), this could become a bottleneck before the Redis backplane migration is ready.

**Mitigation**:
- Monitor WebSocket message throughput and REST latency during B2 integration testing
- The Redis backplane migration path is documented (security-and-operations.md Section 9.6) but non-trivial — requires pub/sub bridging and distributed consumer groups
- Acceptable for MVP (hundreds of connections). Flag for revisit if targeting >50 concurrent agents

**Status**: OPEN — acceptable for MVP
**Sprint**: Post-B2, revisit during Sprint C/D
**Decision refs**: 17, 33

---

### R3: Dual-Write Consistency — Message + AuditEvent (Sprint B2) — MEDIUM

**Risk**: During job execution, agents emit both Messages (AGENT_FINDING, TOOL_SUMMARY) and AuditEvents (TOOL_CALL, TOOL_RESULT) for related but different audiences. Four different producers create messages (surfaces, DispatchService, agent process, PolicyService). Inconsistency between the two streams could cause confusion — UI shows a finding, but audit trail is missing the corresponding tool call, or vice versa.

**Mitigation**:
- Agent-side emission should be atomic per tool call: emit AuditEvent first (compliance), then Message (UX). If Message fails, AuditEvent still exists.
- Consider a helper in the agent process that emits both in sequence to reduce coordination bugs
- Integration tests in B2 should verify Message/AuditEvent correspondence for a job

**Status**: OPEN
**Sprint**: B2
**Decision refs**: 42, 44

---

### R4: Sprint C UI Scope — MEDIUM

**Risk**: Sprint C specifies 6 views (session workspace, fleet dashboard, event stream, activity feed, job inspector, incident workspace foundation). Building a production-quality React frontend with WebSocket state management, structured message rendering, and approval workflows is significant effort — even with AI acceleration.

**Mitigation**:
- Ship with 2-3 views initially: **session workspace** (core value), **fleet dashboard** (operational), **activity feed** (wow factor)
- Event stream view and job inspector can be Sprint D
- Incident workspace is already marked as Sprint D foundation
- Use a component library (shadcn/ui, Radix) to avoid custom UI work

**Status**: OPEN
**Sprint**: C
**Decision refs**: 25, 45

---

### R6: DispatchService Becoming a God Service — HIGH

**Risk**: DispatchService currently owns 4 distinct responsibilities: job creation (with session auto-creation), capability-aware agent matching, job lifecycle (complete/fail/cancel), and agent lifecycle (register/heartbeat/reassign). It's also the source for SYSTEM_EVENT messages, multiple Prometheus metrics, audit events for both job and agent lifecycle, and is a dependency of EventService. Sprint D adds policy enforcement, priority-based dispatch, and inter-agent query routing — all of which compound into a single service that is hard to test, hard to reason about, and the bottleneck for every change.

**Natural seams for extraction**:
- **AgentRegistryService** — `register_agent()`, `heartbeat()`, `reassign_disconnected()`, agent lifecycle audit events. Agent lifecycle is independent of job lifecycle.
- **JobLifecycleService** or keep in DispatchService — `complete_job()`, `fail_job()`, `cancel_job()`. These are state transitions, not dispatch logic.
- **DispatchService** (narrowed) — `create_job()`, `dispatch_pending()`. Pure dispatch: match jobs to agents, push notifications.

**Mitigation**:
- Acceptable as-is through Sprint B — the service is manageable at 7 methods
- Watch for the trigger: when Sprint D policy enforcement and inter-agent query routing land, evaluate extraction
- The existing Decision 2 note ("if the combined repository becomes unwieldy, split it") applies equally to the service layer
- Extract AgentRegistryService first — it has the cleanest boundary and the highest write volume (heartbeats)

**Status**: OPEN — monitor through Sprint B, evaluate before Sprint D
**Sprint**: Pre-D planning
**Decision refs**: 2, 16, 40

---

### R5: No Load Testing or Capacity Planning — LOW (for now)

**Risk**: Docs are thorough on correctness but silent on performance. Unknown: events/second through dedup pipeline, WebSocket throughput per agent, PostgreSQL write volume at scale (100 agents, each emitting AuditEvents per tool call).

**Mitigation**:
- Not a blocker for MVP
- Add basic load test script in Sprint C or D (locust or k6 against the API)
- Instrument early — the telemetry primitives from Sprint A (Decision 26) will surface bottlenecks naturally
- PostgreSQL write volume is the most likely bottleneck: AuditEvents are high-volume, append-only — consider batch inserts in AuditService flush

**Status**: OPEN — defer to post-MVP
**Sprint**: Post-D
**Decision refs**: 26, 32, 42

---

## Follow-Up Items

### F1: LangGraph Version Pinning Strategy

**Context**: LangGraph and LangChain are fast-moving projects with breaking changes between minor versions. The agent runtime depends on `StateGraph`, `ToolNode`, and the checkpointer interface.

**Action**: Pin exact versions in `pyproject.toml` after B2 stabilizes. Document which LangGraph APIs are used and where, so upgrades can be assessed quickly.

**Status**: OPEN
**Sprint**: B2

---

### F2: Sprint C MVP Scope Decision

**Context**: Full Sprint C is ambitious even with parallel worktrees. Need to decide which views ship in C vs. defer to D.

**Action**: Before starting Sprint C, decide: session workspace + fleet dashboard + activity feed as C deliverables, event stream + job inspector deferred to D. Or adjust based on how B2 lands.

**Status**: OPEN
**Sprint**: Pre-C planning

---

### F3: React UI Technology Choices

**Context**: Sprint C specifies React + TypeScript but doesn't lock down state management, component library, or build tooling.

**Action**: Decide before Sprint C:
- State management: React Query (REST) + raw WebSocket hooks (streaming)
- Component library: shadcn/ui or Radix (recommendation)
- Build tool: Vite
- Routing: React Router or TanStack Router

**Status**: OPEN
**Sprint**: Pre-C planning

---

### F4: PostgreSQL AuditEvent Write Volume

**Context**: At scale, AuditEvents are the highest-volume write. Every tool call during every job emits one. A ReAct loop with 10 tool calls per job, 50 concurrent agents = 500 AuditEvent writes in a burst.

**Action**: AuditService already uses async buffered flush (Decision 32). Verify batch insert size is tunable. Consider partitioning `audit_events` table by month if volume grows.

**Status**: OPEN
**Sprint**: D (when audit sinks are fully integrated)

---

## Resolved Items

_None yet — items move here when resolved._

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial version. Risks R1-R5 and follow-ups F1-F4 from architecture review. |
| 2026-03-29 | Added R6: DispatchService god service risk. Identified natural extraction seams (AgentRegistryService). |
