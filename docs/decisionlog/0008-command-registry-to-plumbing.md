# ADR-0008: Move Command Registry to plumbing/

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: garyellis

## Context

The command registry (`register_command` decorator + `get_registry` lookup) is a pure-stdlib utility with zero legion imports. It lived in `legion/cli/registry.py`, making it inaccessible to other entry points without cross-surface imports.

The `architecture` subcommand is a development harness (dependency checks, type checking, dead code detection) that end users should not have installed. Separating it into its own entry point requires the registry to be importable from a layer below surfaces.

The decision tree asks: "Utility, config base, or cross-cutting concern?" → `plumbing/`.

## Decision

Move the command registry to `legion/plumbing/registry.py`. Delete the old `legion/cli/registry.py` with no deprecation shim — all import sites are updated in the same change.

Key design choices:

- **`plumbing/` not `core/`**: The registry has no domain knowledge. It's a generic decorator + list pattern. `core/` is for "one API call returning data" with domain awareness.
- **No multi-registry or tagging**: A single `_registry` list is sufficient. Entry points control which command modules they import; the registry just collects what's been decorated.
- **`register_with_typer()` stays in `cli/main.py`**: It depends on Typer, a surface-specific dependency. The registry is framework-agnostic; the Typer wiring is not.

## Alternatives Considered

1. **Leave in `cli/` and duplicate for dev entry point** — Rejected: violates DRY. Two registries with identical code in different surfaces.
2. **Abstract registry class with pluggable backends** — Rejected: YAGNI. The 12-line module is sufficient for the foreseeable use cases.
3. **Keep old location as a deprecation shim** — Rejected: project convention is to avoid backwards-compatibility hacks when all callers are known and updated.

## Consequences

- Any entry point (`legion-cli`, a future `legion-dev`, CI tooling) can use `from legion.plumbing.registry import register_command` without violating layer rules.
- Enables separating dev-only commands (architecture checks) from user-facing commands in a future change.
- No new dependencies introduced.
