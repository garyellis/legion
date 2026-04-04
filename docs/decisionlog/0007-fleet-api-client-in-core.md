# ADR-0007: Place Fleet API Client in core/fleet_api/

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: garyellis

## Context

The Legion CLI needs to communicate with the Fleet API control plane over HTTP to manage organizations, agent groups, and agents. Multiple surfaces (CLI, Slack, TUI) will eventually need the same Fleet API access. The question is where the HTTP client belongs in the layer model.

The project's decision tree (from CLAUDE.md) asks:

```
Utility, config base, or cross-cutting concern?              -> plumbing/
One API call returning data?                                  -> core/<domain>/
Coordinates multiple APIs or applies business rules?          -> services/
Parses input or formats output for a specific medium?         -> surface layer
```

Each Fleet API client method wraps a single HTTP call and returns a typed response model. There is no business logic, no coordination across APIs, and no surface-specific formatting.

## Decision

Place the Fleet API client in `core/fleet_api/` with the following structure:

```
legion/core/fleet_api/
  __init__.py
  client.py      # FleetAPIClient (httpx) + FleetAPI Protocol + FleetAPIError
  config.py      # FleetAPIConfig (LEGION_FLEET_* env vars, shared across surfaces)
  models.py      # Flat Pydantic response models (OrgResponse, AgentGroupResponse, AgentResponse)
```

Key design choices:

- **`core/` not `services/`**: The client is a thin HTTP wrapper ("one API call returning data"), not a coordinator. It has no business rules.
- **`core/` not a surface**: Placing the client in `cli/` would force other surfaces to duplicate it or illegally import across surfaces.
- **`FleetAPI` Protocol**: Defined alongside the client so any surface can depend on the interface, not the httpx implementation. Enables testing with stubs.
- **`FleetAPIConfig` in `core/`**: Connection settings (URL, API key) are not CLI-specific. Any surface that needs the Fleet API reads `LEGION_FLEET_*` env vars through this shared config.
- **`FleetAPIError(CoreError)`**: Uses the `CoreError` intermediate class so callers can distinguish infrastructure failures from business logic errors without catching all `LegionError`.

## Alternatives Considered

1. **Client in `cli/`** -- Would work initially but violates the cross-surface reuse goal. When Slack or TUI needs Fleet API access, the client would need to move or be duplicated. Rejected: surfaces must not import from each other.

2. **Client in `services/`** -- Services coordinate multiple APIs or apply business rules. The Fleet API client does neither; it's a typed HTTP wrapper. Placing it in services would blur the layer distinction and set a precedent for putting all API clients in services. Rejected: does not match the decision tree.

3. **Client in `plumbing/`** -- Plumbing is for cross-cutting concerns with no Legion domain knowledge. The Fleet API client knows about organizations, agent groups, and agents. Rejected: too domain-aware for plumbing.

4. **No shared client; each surface builds its own** -- Maximum surface independence but duplicates HTTP error handling, auth header injection, and response parsing. Rejected: unnecessary duplication for identical behavior.

## Consequences

- Any surface can import `from legion.core.fleet_api.client import FleetAPIClient` without violating layer rules.
- `core/` gains a dependency on `httpx` (documented in ADR-0006).
- Response models in `core/fleet_api/models.py` must stay in sync with domain models. Contract tests (`test_core_fleet_api_contract.py`) enforce this.
- If a future surface needs async HTTP, an `AsyncFleetAPIClient` can be added to the same package behind the same `FleetAPI` Protocol.
