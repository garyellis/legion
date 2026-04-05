# Architecture

This is the `legion` platform — an SRE and Platform Engineering toolkit.
Business logic is written once in a headless core, then exposed through CLI, Slack, HTTP API, TUI, and AI agents without duplication.

---

## The Mental Model

Every feature follows three stages:

1. **Truth** — Raw data and logic (`core/`). Framework-free. Testable alone.
2. **Preparation** — Coordination, state, and business rules (`services/`).
3. **Painting** — Rendering for a specific medium (`cli/`, `slack/`, `api/`, `tui/`).

If you remember nothing else: **imports flow down, callbacks flow up, no exceptions.**

---

## Layers

```
              ┌────────┬────────┬────────┬────────┐
              │  cli/  │ slack/ │  api/  │  tui/  │   SURFACES (parse input, format output)
              └───┬────┴───┬────┴───┬────┴───┬────┘
                  │    ┌───┴────────┴───┐    │
                  │    │    agents/     │    │       AI RUNTIME (ReAct loops, chains, personas)
                  │    └───────┬────────┘    │
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │   services/    │    │       ORCHESTRATION (state, scheduling, cross-API coordination)
                  │    └───────┬────────┘    │
                  ├────────────┼─────────────┤
                  │    ┌───────┴────────┐    │
                  │    │    domain/     │    │       ENTITIES (cross-cutting business models)
                  │    └───────┬────────┘    │
                  └────────────┼─────────────┘
                       ┌───────┴────────┐
                       │     core/      │             FOUNDATION (one API = one module, SDK wrappers)
                       └────────────────┘
         ┌─────────────────────────────────────────┐
         │            plumbing/                     │  INFRASTRUCTURE (config, logging, database, exceptions)
         │  Available to ALL layers above            │  Every layer imports from plumbing/
         └─────────────────────────────────────────┘
```

### `plumbing/` — "I'm the shared infrastructure"

Cross-cutting utilities that every layer depends on: configuration, logging, database engine, exception hierarchy, and scheduler. This is the foundation beneath the foundation.

- **Imports**: Only stdlib + `pydantic-settings`, `sqlalchemy`, `apscheduler`. Never imports from `legion/` layers.
- **Every layer** (`core/`, `domain/`, `services/`, `agents/`, surfaces) may import from `plumbing/`.
- **Key modules**:
  - `config/` — Configuration system (see dedicated section below)
  - `logging.py` — `setup_logging()` with text/JSON output, called once per surface at startup
  - `database.py` — SQLAlchemy `Base`, `create_engine()`, `create_all()` with SQLite thread-safety defaults
  - `exceptions.py` — `LegionError` base with `retryable` hint, `to_dict()` serialization
  - `scheduler.py` — `SchedulerService` APScheduler wrapper for background jobs

### `core/` — "I talk to one external API"

Pure functions and SDK wrappers. Each subdirectory is one infrastructure domain (openstack, network, slack, etc.). Models are colocated with the logic that produces them — `VMInstance` lives next to `OpenStackCompute`, not in a separate models package.

- **Imports**: Only stdlib + external SDKs + `plumbing/`. Never imports from other `legion/` layers.
- **Test strategy**: Integration tests against real or mocked SDKs.

```python
# core/openstack/compute.py
class OpenStackCompute:
    def __init__(self, config: OpenStackConfig) -> None: ...
    def list_vms(self, ...) -> list[VMInstance]: ...
```

### `domain/` — "I'm a concept that spans multiple APIs"

Pure Pydantic models for business entities that cross core boundaries. No logic, no API calls, no persistence.

- **Litmus test**: Does this entity involve decisions across multiple core domains? Yes → `domain/`. Maps 1:1 to an SDK response? → stays in `core/`.
- **Current**: `Incident` (lifecycle state machine with severity, status, commander, timing).

### `services/` — "I coordinate multiple core modules and remember state"

Stateful coordinators that own persistence, scheduling, and cross-domain workflows.

- **Imports**: From `plumbing/`, `core/`, and `domain/`. Never from agents or surfaces.
- **Communication**: Outward via injected callbacks, never direct surface imports.
- **Litmus test**: Does this need a constructor with injected dependencies? Yes → service. Pure function? → `core/`.

```python
class IncidentService:
    def __init__(self, repository, *, on_incident_created=None):
        self._repo = repository
        self._on_created = on_incident_created  # Callback, not import
```

**The distinction from core is statefulness.** Core orchestrators are stateless pipelines (fetch → filter → return). Services maintain state across calls.

### `agents/` — "I'm the AI runtime"

LLM agent infrastructure: persona configs and simple chains. Currently contains chain agents only (Scribe, Post-Mortem). Graph agent infrastructure (ReAct loop, tool interception, context management) is planned.

Two kinds of agents — don't conflate them:

| Type | Infrastructure | Example |
|:-----|:---------------|:--------|
| **Graph agent** (full ReAct) | Planned: `graph.py`, `evaluator.py`, `tool_interceptor.py` | Incident Commander, Performance Engineer |
| **Chain agent** (LCEL pipeline) | `prompt \| llm \| StrOutputParser()` — no graph | Scribe, Post-Mortem generator |

- **Personas** (`agents/personas/`) define what a graph agent knows: system prompt, tool list.
- **Chains** (`agents/chains/`) are simple pipelines. Three lines, no graph.

### Surfaces — `cli/`, `slack/`, `api/`, `tui/`

Independent consumers of the layers below. Thin. Parse input, call logic, format output.

- Never imported by anything else. No surface imports from another surface.
- Formatting is a surface concern. Rich tables in `cli/views/`, Block Kit in `slack/views/`, JSON in `api/`.
- Each surface is a standalone entry point with its own DI wiring at startup.

**Current state**: `cli/` and `slack/` are implemented. `api/` and `tui/` are empty placeholders.

Persistent startup paths in `api/` and `slack/` validate that the runtime
database is already at Alembic head before serving. Deploy-time schema
changes live behind `legion-cli db upgrade`. Explicit test fixtures may still
use `create_all()` against `sqlite:///:memory:` directly.

---

## Directory Structure

```
legion/
├── core/                              # FOUNDATION: Headless infrastructure adapters
│   ├── exceptions.py                  # Core-layer exception types
│   ├── openstack/                     # OpenStack cloud operations
│   │   ├── models.py                  #   VMInstance, HypervisorResource, QuotaUsage
│   │   ├── compute.py                 #   Manager: list, find, start, stop, reboot
│   │   └── orchestrator.py            #   Batch ops, filtering, ThreadPoolExecutor
│   ├── network/                       # Network utilities
│   │   ├── models.py                  #   Network-specific data models
│   │   ├── dns_check.py              #   DNSMigrationManager + DNS models
│   │   ├── ssh_client.py             #   SSH context manager (Paramiko)
│   │   └── wol.py                    #   Wake-on-LAN with Pydantic validation
│   └── slack/                         # Slack API wrapper (SDK operations, not bot logic)
│       ├── client.py                  #   SlackClient: post_message, create_channel, etc.
│       ├── config.py                  #   SlackConfig (SLACK_* env vars)
│       └── models.py                  #   Slack-specific data models
│
├── domain/                            # ENTITIES: Cross-cutting business models
│   └── incident.py                    # Incident, IncidentSeverity, IncidentStatus, IncidentBuilder
│
├── services/                          # ORCHESTRATION: Stateful business coordination
│   ├── exceptions.py                  # Service-layer exception types
│   ├── repository.py                  # IncidentRepository ABC + InMemory + SQLite impls
│   └── incident_service.py            # Incident lifecycle coordinator (callbacks for stale/resolved)
│
├── agents/                            # AI RUNTIME: Agent infrastructure
│   ├── config.py                      # AgentConfig (model/provider settings)
│   ├── exceptions.py                  # Agent-layer exception types
│   ├── personas/                      # Graph agent configs (planned)
│   └── chains/                        # Simple LLM pipelines (no ReAct graph)
│       ├── scribe.py                  #   AI-generated incident updates
│       └── post_mortem.py             #   Post-incident report generation
│
├── cli/                               # SURFACE: Terminal
│   ├── main.py                        # Typer app bootstrap
│   ├── registry.py                    # CLI command registry
│   ├── commands/                      # Command handlers
│   │   ├── db.py                      #   Alembic inspection + upgrade commands
│   │   ├── lab.py                     #   OpenStack lab commands
│   │   ├── network.py                 #   DNS, SSH, WoL commands
│   │   └── shout.py                   #   Slack integration commands
│   └── views/                         # Rich rendering
│       ├── base.py                    #   Shared view utilities
│       ├── db.py                      #   DB migration status/history output
│       ├── lab.py                     #   OpenStack output formatting
│       └── network.py                 #   Network output formatting
│
├── slack/                             # SURFACE: Slack
│   ├── main.py                        # Bolt app bootstrap, DI wiring, Socket Mode entry
│   ├── manifest.py                    # Slack app manifest generator
│   ├── registry.py                    # Slack command registry
│   ├── commands/                      # Deterministic slash commands
│   │   ├── lab.py                     #   OpenStack commands via Slack
│   │   └── network.py                 #   Network commands via Slack
│   ├── incident/                      # Incident Commander bot
│   │   ├── models.py                  #   SlackIncidentState, SlackIncidentIndex ABC, InMemorySlackIncidentIndex
│   │   ├── persistence.py             #   SQLiteSlackIncidentIndex (database-backed)
│   │   ├── handlers.py                #   Slack event/interaction handlers
│   │   └── wiring.py                  #   Handler registration
│   └── views/                         # Block Kit rendering
│       ├── base.py                    #   Shared Block Kit utilities
│       ├── incident.py                #   Incident dashboard/status views
│       ├── lab.py                     #   OpenStack output for Slack
│       └── network.py                 #   Network output for Slack
│
├── api/                               # SURFACE: HTTP/Webhooks (placeholder)
│
├── tui/                               # SURFACE: Terminal UI (placeholder)
│
├── plumbing/                          # INFRASTRUCTURE: Shared across all layers
│   ├── config/                        # Configuration system
│   │   ├── __init__.py                #   Re-exports LegionConfig, PlatformConfig
│   │   ├── base.py                    #   LegionConfig (pydantic-settings base class)
│   │   ├── platform.py                #   PlatformConfig (LEGION_* env vars)
│   │   ├── database.py                #   DatabaseConfig (DATABASE_* env vars)
│   │   └── telemetry.py               #   TelemetryConfig (TELEMETRY_* env vars)
│   ├── logging.py                     # setup_logging() — text/JSON, stdout/stderr
│   ├── database.py                    # SQLAlchemy Base, create_engine(), create_all()
│   ├── exceptions.py                  # LegionError base with retryable + serialization
│   └── scheduler.py                   # SchedulerService (APScheduler wrapper)
│
└── main.py                            # Thin bootstrap → cli/main.py
```

---

## Dependency Rules

```
plumbing/  → imports NOTHING from legion (only stdlib + pydantic-settings, sqlalchemy, apscheduler)
core/      → imports from plumbing/ only (plus stdlib + external SDKs)
domain/    → imports from plumbing/ and core models (type references, never logic)
services/  → imports from plumbing/, core/, and domain/
agents/    → imports from plumbing/, core/, domain/, services/
surfaces   → import from any layer below
```

- `plumbing/` is the bedrock — importable by every layer, imports from none.
- No lateral imports between surfaces. `cli/` never imports from `slack/`.
- Callbacks flow upward (services → surfaces via injected callables). Imports flow downward.
- `core/` never imports LangChain, Rich, Slack SDK, or FastAPI.

---

## Interaction Patterns

| Pattern | Trigger | Logic | Example |
|:--------|:--------|:------|:--------|
| **Deterministic** | User runs CLI command or Slack slash command | Surface → `core/` directly | `vm-list`, `dns-check` |
| **Orchestrated** | User triggers multi-step workflow | Surface → `services/` → multiple `core/` modules | Incident create → resolve |
| **Reactive** | User mentions agent in Slack | Surface → `agents/` ReAct loop → `core/` tools | `@SREBot fix the VM` |
| **Proactive** | Webhook fires (Alertmanager, Datadog) | `api/` → `services/` → optional `agents/` triage | Auto-incident creation |

~60% of commands are pass-throughs (surface → core directly). ~40% need real orchestration via services. Don't force everything through a service layer.

---

## Configuration System

Configuration lives in `plumbing/config/` and follows two rules: **12-factor** (env vars for secrets and deployment values) and **only configure what you run** (unused components never fail).

### How It Works

All config classes extend `LegionConfig` (a `pydantic-settings` `BaseSettings` subclass). Each domain defines its own config class with a unique env var prefix. Surfaces instantiate only the configs they need at startup.

```python
# core/slack/config.py
from legion.plumbing.config import LegionConfig

class SlackConfig(LegionConfig):
    model_config = SettingsConfigDict(env_prefix="SLACK_")
    bot_token: SecretStr
    app_token: SecretStr
    log_level: str = "INFO"
```

```python
# slack/main.py — surface creates and injects config
slack_config = SlackConfig()            # fails fast if SLACK_* vars missing
slack_client = SlackClient(slack_config)  # config injected, not self-instantiated
```

### Two Kinds of Configuration

| Kind | Examples | Source | Committed? |
|:-----|:---------|:-------|:-----------|
| **Environment** | API keys, endpoints, tokens, log level | Env vars via `pydantic-settings` | Never |
| **Structural** | Agent persona tool lists, failover step sequences, alert routing rules | YAML files validated by Pydantic (planned) | Yes |

### Built-in Config Classes

| Class | Prefix | Purpose |
|:------|:-------|:--------|
| `LegionConfig` | (base) | Shared behavior: `is_available()`, `to_redacted_dict()` |
| `PlatformConfig` | `LEGION_` | `log_level`, `environment` |
| `DatabaseConfig` | `DATABASE_` | `url`, `pool_pre_ping`, `echo` |
| `TelemetryConfig` | `TELEMETRY_` | `enabled`, `endpoint`, `service_name` |

Domain configs live alongside the code that uses them — `core/slack/config.py`, `agents/config.py`.

### Key Rules

- **Prefix all env vars.** `OPENSTACK_AUTH_URL`, `SLACK_BOT_TOKEN`, `AGENT_MODEL_NAME`. Prevents collisions.
- **Defaults for non-secrets only.** Region, API version, model name get defaults. Secrets never do.
- **Inject config, don't self-instantiate.** Surfaces create config objects and pass them to constructors. This makes dependencies explicit and testing straightforward.
- **Fail fast.** Config objects are created at process startup. Missing env vars crash immediately, not 30 minutes into a request.
- **No global singleton.** Each process composes its own config. There is no `settings.py` that imports everything.
- **`SecretStr` for secrets.** Prevents accidental logging. `to_redacted_dict()` masks secrets safely.

### Config Per Process

| Process | Config Classes |
|:--------|:---------------|
| `legion-cli` | `PlatformConfig`, `OpenStackConfig`, `NetworkConfig` (only what the invoked command needs) |
| `legion-slack` | `PlatformConfig`, `SlackConfig`, `DatabaseConfig`, `AgentConfig` (optional) |

A container running `legion-cli` never touches `SlackConfig`. Missing Slack tokens cause no errors because that config class is never instantiated.

---

## Persistence

The project uses SQLAlchemy with support for SQLite (local dev, single-node) and PostgreSQL (production, multi-instance).

### How It Works

- **`plumbing/database.py`** provides the shared `Base`, `create_engine()`, and `create_all()`. All ORM models inherit from this single `Base`.
- **`plumbing/config/database.py`** provides `DatabaseConfig` reading `DATABASE_URL` etc. from environment.
- **`plumbing/config/db_admin.py`** provides operator-only direct DB config via `LEGION_DB_*` for `legion-cli db ...`.
- **`plumbing/migrations.py`** owns Alembic history/current/head inspection, explicit upgrades, and startup validation that the DB is already current.
- **Repository pattern**: Each domain has an ABC (e.g., `IncidentRepository`) with in-memory and SQLite implementations. Tests run contract suites against both.
- **Engine sharing**: Surfaces create one engine at startup and pass it to all repositories. One connection pool, one database.
- **SQLite quirks**: `create_engine()` automatically sets `check_same_thread=False`. The `_ensure_utc()` helper in repository code reattaches timezone info to naive datetimes returned by SQLite.

### Current ORM Models

| Table | ORM Class | Location |
|:------|:----------|:---------|
| `incidents` | `IncidentRow` | `services/repository.py` |
| `slack_incident_state` | `SlackIncidentStateRow` | `slack/incident/persistence.py` |

---

## Security Model

- **Graceful degradation**: Bots work identically without AI — if the LLM is unreachable, the bot still handles deterministic commands.
- **Least privilege** (planned): Each agent persona gets only the tools it needs.
- **Tool interception** (planned): Gate destructive operations behind human approval.

---

## Package Dependencies

Core dependencies are in `pyproject.toml`. Optional extras isolate heavier dependencies:

```toml
[project.optional-dependencies]
agents = ["langchain-openai>=0.3", "langchain-core>=0.3"]
postgres = ["psycopg[binary]>=3.1"]
```

Install only what you need: `uv sync`, or `uv sync --extra agents --extra postgres`.

### Entry Points

| Script | Module | Purpose |
|:-------|:-------|:--------|
| `legion-cli` | `legion.main:main` | CLI (Typer) |
| `legion-slack` | `legion.slack.main:main` | Slack bot (Socket Mode) |
| `legion-slack-manifest` | `legion.slack.manifest:main` | Generate Slack app manifest |
