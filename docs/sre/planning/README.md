# SRE Agent Fleet — Planning Documents

> **These are living documents.** Update them in place. Do not create new files to capture revisions — edit the existing ones. Each document has a changelog section at the bottom for tracking significant changes.

---

## Philosophy

Legion is an SRE and Platform Engineering toolkit built on first principles:

1. **Write business logic once, expose it everywhere.** A headless core with thin surfaces (CLI, Slack, API, TUI, agent process). No logic duplication across surfaces.

2. **Imports flow down, callbacks flow up, no exceptions.** The layer model is strict. Violations compound into coupling that makes the system brittle.

3. **Only build what you need.** Most commands are pass-throughs. Services exist for genuine cross-domain orchestration. Don't force indirection where it doesn't exist.

4. **Design before build.** The system has distributed state, security boundaries, and multi-surface coordination. Each phase is architecturally resolved before coding begins. Structural design precedes implementation.

5. **Deliver value vertically, not horizontally.** Each sprint delivers end-to-end functionality — from configuration to execution to output. A working agent with a minimal CLI is more valuable than a complete CLI dispatching to nothing.

6. **The existing system keeps working throughout.** The incident bot, CLI, and Slack integration continue functioning as the fleet is built alongside them.

### Quality Attributes

| Attribute | What It Means for Legion |
|:----------|:-------------------------|
| **Maintainability** | Layer boundaries prevent coupling. Each module has one reason to change. Tests enforce dependency direction. |
| **Extensibility** | New core domains, agent groups, tools, and surfaces are additive. Zero changes to existing code. |
| **Reliability** | Database is the durability layer. WebSocket is delivery, not storage. Jobs survive disconnects. Agents reconnect automatically. |
| **User Experience** | Operators get a responsive, conversational interface. Streaming results. Session continuity. Fleet-wide visibility. |
| **Developer Experience** | Clear placement rules. Tests against real SQL (`sqlite:///:memory:`). One command to run anything. |

---

## Documents

| Document | What It Covers |
|:---------|:---------------|
| [Architecture](./architecture.md) | System topology, layer model, component overview, how everything fits together |
| [Domain Model](./domain-model.md) | All entities, relationships, state machines, field definitions |
| [API Contracts](./api-contracts.md) | REST endpoints, WebSocket protocol, request/response schemas, error handling |
| [Services and Persistence](./services-and-persistence.md) | Service interfaces, repositories, DI wiring, data flow diagrams |
| [Decisions](./decisions.md) | All architectural decisions with problem, options, rationale |
| [Build Sprints](./build-phases.md) | Sprint-based delivery plan (A, B1/B2, C, D) with parallelizable work items |
| [Agent Runtime](./agent-runtime.md) | Agent process, AI runtime, knowledge layer, tools, guardrails |
| [Security and Operations](./security-and-operations.md) | Secrets, credentials, auth, audit log, messaging reliability, deployment, observability |
| [Threat Model](./threat-model.md) | STRIDE analysis, attack surfaces, LLM threats, plugin security, mitigations |

### How to Use These Docs

- **Building a feature?** Start with [Architecture](./architecture.md) for placement rules, then [Domain Model](./domain-model.md) for entity contracts, then [API Contracts](./api-contracts.md) for endpoint specs.
- **Making a design decision?** Add it to [Decisions](./decisions.md) with problem statement, options, rationale.
- **Planning work?** Check [Build Sprints](./build-phases.md) for dependencies and parallelization.
- **Working on agents?** See [Agent Runtime](./agent-runtime.md) for the AI runtime, tools, and knowledge layer.

### Operator Day 1

The sprint structure is optimized to deliver the "aha moment" as fast as possible:

```bash
# 1. Start everything (no Slack required)
docker compose up -d

# 2. Configure the fleet
legion-cli fleet org create --name acme
legion-cli fleet agent-group create --org acme --name prod-aks
legion-cli fleet agent-group token prod-aks
# → LEGION_REGISTRATION_TOKEN=abc123

# 3. Start an agent (cluster creds already in env)
LEGION_API_URL=http://localhost:8000 \
LEGION_REGISTRATION_TOKEN=abc123 \
KUBECONFIG=~/.kube/config \
legion-agent

# 4a. Talk to it (CLI)
legion-cli session start --group prod-aks \
  --message "what pods are crashlooping in namespace payments?"
# → Agent investigating...
# → Found 2 crashlooping pods...

# 4b. Or point a webhook at it (Alertmanager, Datadog, etc.)
legion-cli fleet event-source create --org acme --group prod-aks \
  --source alertmanager --name "Prod Alertmanager"
# → WEBHOOK_URL=http://localhost:8000/events/ingest/alertmanager
# → AUTH_TOKEN=evt_abc123
# Configure Alertmanager to POST to that URL — agents investigate automatically.
```

Four steps from zero to value — no Slack setup required. Add Slack later as an upgrade path. See [Build Sprints](./build-phases.md) for how this path drives the sprint structure.

### Cross-References

- `docs/ARCHITECTURE.md` — The legion platform layer model and dependency rules (source of truth for the layer diagram)
- `docs/CONTRIBUTING.md` — Developer workflow, placement decision tree, hard rules

---

## Changelog

| Date | Change |
|:-----|:-------|
| 2026-03-29 | Initial curated doc set created from prior planning documents |
| 2026-03-29 | Updated philosophy (vertical delivery), added Operator Day 1 section, updated references for sprint model. |
| 2026-03-29 | Added Threat Model to document index. |
| 2026-03-29 | Architecture review: Sprint B split into B1/B2 milestones. Sprint A expanded (Alembic, API key auth). Decisions 29-33 added. Audit log subsystem (Decision 32) with pluggable sinks. Messaging architecture and WebSocket reliability (Decision 33) with connection lifecycle, failure modes, delivery guarantees. |
| 2026-03-29 | Event architecture: Decisions 34-36. Event as domain model (two-layer: raw envelope + normalized fields). Source adapter pattern with webhook ingestion. Slack-optional deployment for demo/evaluation. Updated all planning docs: domain model, services, API contracts, build phases, architecture. |
