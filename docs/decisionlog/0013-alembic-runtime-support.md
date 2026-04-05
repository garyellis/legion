# ADR-0013: Alembic deploy-time migration support

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: developer

## Context

Legion already has a shared ORM base in `legion.plumbing.database.Base`, and current startup/tests initialize schemas by calling `create_all(engine)`. That is fine for `sqlite:///:memory:` fixtures, but it leaves persistent databases without a migration system. The repo needs Alembic support without pushing schema mutation into API or Slack startup.

There is also a legacy case to preserve: unmanaged persistent databases may already contain Legion tables but no `alembic_version` row. Those databases need a deterministic adoption path that does not drop data or require manual one-off SQL.

## Decision

We keep `legion.plumbing.database.create_all(engine)` as a direct metadata helper for tests and add explicit Alembic operations in the plumbing layer:

- `sqlite:///:memory:` continues to use direct `Base.metadata.create_all(engine)`.
- Operator-facing `legion-cli db ...` commands use dedicated direct DB config (`LEGION_DB_*`) and call `legion/plumbing/migrations.py`.
- Fresh persistent databases are migrated explicitly via `legion-cli db upgrade`.
- Deployment wiring is responsible for running that explicit migration step before persistent Legion surfaces are treated as ready.
- Local development initially satisfies that deploy-time requirement through Docker Compose wiring that runs `legion-cli db upgrade` against the same database URL used by the API.
- API and Slack startup validate `current == head` and fail fast with a clear operator action if the DB is behind.
- Unmanaged persistent databases without a version row are adopted only through the explicit upgrade path.

The Alembic scaffold lives at the repo root (`alembic.ini`, `alembic/env.py`, `alembic/versions/...`) and is wired against the shared `Base.metadata`. This keeps runtime migration behavior centralized in plumbing and avoids editing API or Slack surfaces for this change.

## Dependency Details

| Field | Value |
|:------|:------|
| Package | `alembic` |
| Version | `>=1.18.4,<2` |
| License | MIT |
| PyPI downloads/month | Not published by PyPI |
| Maintainers | Upstream SQLAlchemy project |
| Transitive deps | 2 direct runtime deps (`SQLAlchemy`, `Mako`) |
| Last release | 2026-02-10 |
| Known CVEs | None known for the pinned release at the time of writing |

## Alternatives Considered

1. **Keep `create_all()` as the runtime schema mechanism** - rejected because it gives no revision history, no upgrade path, and no safe baseline for future schema changes.
2. **Run Alembic automatically during API/Slack startup** - rejected because schema mutation on every boot creates rollout races, hides operational steps, and makes failures harder to control in multi-instance deployments.
3. **Force unmanaged databases through `upgrade head` blindly** - rejected because Alembic would try to create tables that may already exist, which is not a deterministic adoption path.

## Consequences

- Persistent schema changes now have a revisioned, explicit operator path.
- In-memory SQLite test fixtures keep their fast direct schema creation path.
- Operators need one extra deploy step: `legion-cli db upgrade`.
- Deployment configuration must wire that step correctly; startup validation is intentionally not a substitute for deploy-time migration execution.
- Legacy persistent databases can be adopted without data loss, but the upgrade command now has to distinguish fresh databases from unmanaged ones.
- Future schema changes must be expressed as Alembic revisions instead of implicit startup mutations.

## References

- [Alembic project on PyPI](https://pypi.org/project/alembic/)
- `docs/features/alembic-runtime-support.md`
