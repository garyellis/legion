# Legion

An operations platform that deploys intelligent agents across your infrastructure to investigate, diagnose, and resolve issues. One interface across all systems and environments, replacing fragmented tooling and manual triage with a unified control plane and agent fleet.

## Status

What works today and what's on the roadmap.

| Component | Status | Description |
|:----------|:-------|:------------|
| CLI (`legion-cli`) | Working | Typer-based CLI with architecture enforcement, lab operations |
| Developer CLI (`legion-dev`) | Working | Internal development harness for architecture gates, ADRs, review, scaffolding, and GitHub issue handoffs |
| Slack bot (`legion-slack`) | Working | Slack Bolt integration with incident management, slash commands |
| REST API (`legion-api`) | Working | FastAPI surface with CRUD routes, WebSocket scaffolding |
| OpenStack adapter | Working | VM lifecycle, compute management, batch orchestration |
| DNS tooling | Working | Migration manager, TTL analysis, cache tracking |
| SSH / WoL | Working | Paramiko SSH client, Wake-on-LAN |
| Incident system | Working | Domain model, service layer, Slack-integrated lifecycle |
| Architecture harness | Working | Enforced gate + advisory checks, pre-commit hook, CI-ready |
| Domain + services layer | Working | Jobs, sessions, agents, fleet, dispatch, filter, repositories |
| Distributed agent fleet | Planned | Agents running inside target environments with local execution |
| WebSocket control plane | Planned | Real-time agent-to-control-plane communication |
| Interactive agent sessions | Planned | Chat-based infrastructure interrogation during incidents |
| Observability integration | Planned | Metrics, logs, and traces as structured agent context |
| Scoped agent credentials | Planned | Agent-local secrets, ephemeral delegated access |

## Architecture

Layered architecture with strict downward-only imports, enforced by static analysis.

```
plumbing/    Base config, exceptions, database (no legion imports)
internal/    Dev tooling, architecture checks (no legion imports)
core/        Infrastructure adapters: OpenStack, DNS, SSH, WoL
domain/      Cross-cutting business entities: incidents, jobs, sessions
services/    Stateful orchestration, repositories, scheduling
agents/      AI runtime: LLM config, chains (scribe, post-mortem)
```

Surfaces (independent entry points, never import each other):

```
cli/         Typer CLI          → legion-cli
cli_dev/     Developer harness  → legion-dev
slack/       Slack Bolt bot     → legion-slack
api/         FastAPI REST API   → legion-api
```

`cli_dev/` is the internal development harness surface. It exists to keep architecture intent, review expectations, ADR workflows, and issue handoff discipline executable instead of tribal knowledge.

## Roadmap

### Distributed Agent Fleet

Agents run inside target environments (Kubernetes clusters, cloud accounts, on-prem) and execute jobs locally with full context and access. Single-job execution model for deterministic behavior. Horizontal scaling via agent groups.

### Event-Driven Incident System

Ingest events from Alertmanager, Datadog, CI/CD, or GitHub and turn them into structured incidents. Automatic incident creation from alerts, job orchestration for investigation and remediation, continuous incident summarization via scribe chain.

### Interactive Agent Sessions

Chat with agents during incidents or on demand. Ask questions about infrastructure state without reaching for kubectl, dashboards, or SSH. Full audit trail of reasoning and actions taken.

### Observability-Native Reasoning

Agents consume metrics, logs, and traces as structured context. Raw signals are transformed into LLM-friendly formats (summarized distributions, trends, anomaly highlights) to enable bottom-up debugging across system layers.

### Secure Execution Model

Clear separation between control plane and execution environment. Agent-local credentials (never centralized), read-only or scoped execution by default, ephemeral delegated access for job-specific actions.

## Development

```bash
uv sync --group dev
uv run pytest                                  # run all tests
uv run legion-dev architecture gate            # dependency direction + banned imports + typecheck + circular + dangerous calls + secrets
uv run legion-dev review                       # repo-aware engineering review prompt
uv run legion-dev adr create "<title>"         # create the next ADR from the template
uv run legion-dev issue create "<title>" --print-template > /tmp/issue.md
uv run legion-dev issue create "<title>" --body-file /tmp/issue.md
uv run legion-dev architecture typecheck       # mypy type checking
uv run legion-dev architecture security        # bandit SAST scan
uv run legion-dev architecture audit           # dependency vulnerability scan
```

Common `legion-dev` workflows:

```bash
uv run legion-dev issue show "<number-or-title>"       # inspect a GitHub issue
uv run legion-dev issue validate "<number-or-title>"   # check readiness for handoff
uv run legion-dev issue handoff "<number-or-title>"    # emit a deterministic handoff prompt
uv run legion-dev issue close "<number-or-title>" --verified "<commands and results>"
uv run legion-dev review                       # load active repo instructions for review
```

Full architecture gate and advisory suite:

```bash
uv run legion-dev architecture gate            # required gate
uv run legion-dev architecture deadcode        # advisory: vulture dead code
uv run legion-dev architecture unused-deps     # advisory: unused dependency detection
uv run legion-dev architecture security        # advisory: bandit SAST
uv run legion-dev architecture audit           # advisory: pip-audit CVE scan
```

## Pre-commit Hook

```bash
git config core.hooksPath .githooks
```

Runs the required architecture gate before every commit, plus advisory security scan.

## Project Guidelines

See [CLAUDE.md](CLAUDE.md) and [AGENTS.md](AGENTS.md) for agent-facing architecture rules and workflow expectations. See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contributor guidance on using the `cli_dev/` harness.
