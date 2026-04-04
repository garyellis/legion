# ADR-0010: Add Project scope to fleet hierarchy

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: developer

## Context

The fleet hierarchy was org → agent-group. Every agent group was a direct child of an organization with no intermediate grouping.

An organization with multiple teams or workloads (platform infra, data pipelines, ML serving) had no way to isolate agent groups by concern. All groups were peers, which makes scoped permissions, configuration inheritance, and ownership delegation impossible without bolting on ad-hoc conventions.

The constraint: agent groups need an isolation boundary within an org that is a first-class entity with its own CRUD, not a label or naming convention.

## Decision

Add a **Project** entity between Organization and AgentGroup: `org → project → agent-group`.

**Domain model** (`legion/domain/project.py`): `id`, `org_id` (FK), `name`, `slug`, timestamps. Same Pydantic pattern as Organization.

**AgentGroup** (`legion/domain/agent_group.py`): gains `project_id` (FK). Keeps `org_id` denormalized — many queries filter by org across projects, and requiring a join for every agent-group lookup adds cost with no benefit.

**Seeded defaults** (`legion/api/main.py`): a "default" org and "default" project are created at startup with well-known UUIDs. This means the system works immediately without explicit setup — agent groups can be created under `default/default` out of the box.

**Full CRUD** across all layers: domain model, `ProjectRow` ORM + repository methods, API routes (`/projects/`), HTTP client + protocol, CLI surface (`project create/list/update/delete`).

## Alternatives Considered

1. **Tags or labels on agent groups** — No schema enforcement, no FK integrity. Isolation becomes a convention that any caller can ignore. Filtering by tag requires scanning all groups rather than a direct FK lookup. Doesn't support scoped permissions without a separate access-control layer on top of freeform strings.

2. **Slug-path convention** (`org/namespace/agent-group`) — Pushes hierarchy into string parsing. No independent CRUD for the namespace — can't rename it, list its children, or attach metadata without parsing slugs everywhere. Fragile under refactoring.

3. **Keep the flat hierarchy and scope later** — Delays the migration cost but means every feature built on the flat model (permissions, config inheritance, audit trails) has to be reworked when the scope is eventually added. The migration cost is lower now with fewer dependents.

## Consequences

- Agent group creation now requires `project_id`. This is a breaking change to the API schema, HTTP client, and CLI.
- All existing tests updated to supply `project_id` on AgentGroup construction.
- The seeded defaults soften the breaking change for development and single-tenant use — no explicit org/project setup required to get started.
- `org_id` on AgentGroup is denormalized. If an agent group moves between projects in different orgs (unlikely but possible), `org_id` must be updated in sync. No automated enforcement yet.
- Follow-up: project-scoped permissions, project-level configuration inheritance, `list_agent_groups` filtering by `project_id` in the CLI.

## References

- `legion/domain/project.py` — domain model
- `legion/api/routes/projects.py` — API routes
- `legion/api/main.py` — seed logic
- `legion/services/fleet_repository.py` — `ProjectRow`, `list_agent_groups_by_project`
