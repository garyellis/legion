# ADR-0014: WebSocket Client Library for Agent Process

**Status**: ACCEPTED
**Date**: 2026-04-05
**Author**: developer

## Context

The agent runner process (Sprint B1) needs a WebSocket client library to connect to the control plane API's `/ws/agents/{agent_id}` endpoint. The server side uses FastAPI/Starlette's built-in WebSocket support, which internally depends on the `websockets` library. The client needs: async WebSocket connections, JSON message send/receive, Bearer token auth via the `Authorization` header, and clean connection lifecycle management. Reconnection is handled by the agent runner's own loop — the library just needs connect, send, and receive.

## Decision

Use `websockets` as the WebSocket client library.

`websockets` is already a transitive dependency — starlette (via FastAPI and uvicorn) depends on it for WebSocket support. Adding it as a direct dependency makes this implicit dependency explicit without pulling in any new packages. The library is async-native, well-maintained, has a clean `connect()` API, and handles the WebSocket protocol correctly. It's pure Python with zero transitive dependencies of its own.

The agent runner's `client.py` will use `websockets.connect(uri)` as an async context manager. Reconnection with exponential backoff is a simple while loop in the agent runner — the library doesn't need to provide this.

## Dependency Details

| Field | Value |
|:------|:------:|
| Package | `websockets` |
| Version | `>=16,<17` |
| License | BSD-3-Clause |
| PyPI downloads/month | ~30M |
| Maintainers | 1 active (Aymeric Augustin) |
| Transitive deps | 0 (pure Python) |
| Last release | 2026-01-10 |
| Known CVEs | None |

## Alternatives Considered

1. **`aiohttp`** — Full async HTTP client with WebSocket support. Rejected: pulls in a complete HTTP client framework (~10 transitive deps) when we only need WebSocket. We already use `httpx` for HTTP (ADR-0006). Adding aiohttp would create two competing HTTP stacks. The WebSocket API is also more verbose than `websockets`.

2. **`websocket-client`** — Popular sync WebSocket library. Rejected: synchronous only. Would require threading to work alongside the async agent event loop. Adds complexity and potential race conditions. The agent runner is async-first.

3. **Raw `asyncio` + HTTP upgrade** — Implement WebSocket protocol manually over `asyncio.open_connection`. Rejected: WebSocket protocol implementation is non-trivial (framing, masking, ping/pong, close handshake). Reimplementing this is error-prone when a well-tested library already exists as a transitive dependency.

## Consequences

- Agent WebSocket client uses `websockets.connect()` with async context manager pattern.
- No new transitive dependencies added to the project (already pulled in by starlette).
- Consistent with server-side: starlette uses websockets internally, so both sides share the same protocol implementation.
- Reconnection, heartbeat, and job dispatch are the agent runner's responsibility, not the library's.
- Version pin should track what starlette/uvicorn already require to avoid conflicts.

## References

- ADR-0006: httpx runtime dependency (similar dependency evaluation pattern)
- Sprint B1 build phases: `docs/sre/planning/build-phases.md`
