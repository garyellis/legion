# ADR-0012: Path-based agent websocket bootstrap target

**Status**: ACCEPTED
**Date**: 2026-04-04
**Author**: codex

## Context

The initial Phase 1 registration flow returned a fully qualified
`websocket_url` from `POST /agents/register`. That made the control plane
responsible for inventing the network authority an agent should use after
registration.

That assumption is false in Legion's real environments:

- a host-local developer may need `localhost`
- a Docker Compose agent may need `api`
- a production agent behind a WAF or load balancer needs the external public
  hostname

The server does not know the agent's reachable authority from the registration
request alone, and using request metadata or proxy headers would couple
bootstrap correctness to ingress behavior.

The real invariant is narrower. The server owns the WebSocket path, auth
contract, and timing metadata. The agent owns the control-plane base URL it can
actually reach from where it runs.

This decision affects the API contract in `legion/api/schemas.py`,
`legion/api/routes/agents.py`, and `legion/core/fleet_api/models.py`, plus
consumer code such as `local/demo_agent.py`.

## Decision

`POST /agents/register` returns a path-based WebSocket bootstrap target instead
of a fully qualified URL.

Concretely:

- `AgentConnectionConfig` exposes `websocket_path`, not `websocket_url`
- `legion/api/routes/agents.py` returns `"/ws/agents/{agent_id}"`
- `legion/core/fleet_api/models.py` mirrors the same path-based contract
- the agent/runtime composes the final `ws://` or `wss://` endpoint from its
  own configured control-plane base URL plus the returned path

This keeps authority selection at the edge where it belongs. The server
describes the protocol contract. The agent applies its local deployment
knowledge.

## Alternatives Considered

1. **Return a fully qualified `websocket_url` from server config** — rejected
   because a single configured authority is not correct across localhost
   development, Docker Compose network development, and production behind a WAF
   or load balancer. It makes the control plane pretend it knows the agent's
   network vantage point when it does not.
2. **Reflect request host and scheme metadata** — rejected because bootstrap
   correctness would depend on ingress and proxy header behavior. That creates a
   hidden trust boundary and still does not solve mixed-topology development.
3. **Return multiple candidate authorities now** — rejected because it widens
   the contract into endpoint selection and failover behavior before Legion has
   chosen an active/active strategy. That is unnecessary scope for Sprint A.

## Consequences

- The registration contract now works cleanly for host-local development,
  Compose-network agents, and WAF/LB production because the agent can use its
  own reachable base URL.
- The API no longer needs `API_PUBLIC_BASE_URL` to build bootstrap responses,
  which simplifies control-plane configuration.
- Consumers must compose the final WebSocket authority locally. Existing demo
  or runtime clients that assumed direct unauthenticated WebSocket connections
  must adopt the registration-first flow.
- This preserves room for later active/active work. If Legion eventually needs
  multiple advertised endpoints or failover policy, that can be added as a new
  decision instead of being implicitly baked into Sprint A registration.

## References

- `legion/api/routes/agents.py`
- `legion/api/schemas.py`
- `legion/core/fleet_api/models.py`
- `local/demo_agent.py`
- `docs/features/phase-1-agent-group-registration-flow.md`
- `docs/sre/planning/api-contracts.md`
