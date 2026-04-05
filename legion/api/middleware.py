"""API middleware for authentication and request metrics."""

from __future__ import annotations

import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

from legion.plumbing import telemetry

_PUBLIC_PATHS = frozenset({
    "/health",
    "/health/ready",
    "/docs",
    "/metrics",
    "/openapi.json",
    "/agents/register",
})
_PUBLIC_PREFIXES = ("/ws/",)


def _route_template(request: Request) -> str:
    """Resolve the matched route pattern for stable metrics labels."""
    route = request.scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(template, str):
        return template

    scope = request.scope
    for candidate in request.app.router.routes:
        match, _ = candidate.matches(scope)
        if match == Match.FULL:
            candidate_template = getattr(candidate, "path_format", None) or getattr(candidate, "path", None)
            if isinstance(candidate_template, str):
                return candidate_template

    return request.url.path


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header on non-public routes.

    If *api_key* is empty, all requests pass through (dev mode).
    """

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        path = request.url.path
        if self._api_key:
            if path not in _PUBLIC_PATHS and not path.startswith(_PUBLIC_PREFIXES):
                provided = request.headers.get("X-API-Key", "")
                if provided != self._api_key:
                    return Response(
                        content=json.dumps({"detail": "Invalid or missing API key"}),
                        status_code=401,
                        media_type="application/json",
                    )

        return await call_next(request)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Record API request counters and latency for all HTTP requests."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        path = _route_template(request)
        start = time.perf_counter()
        response = await call_next(request)
        telemetry.api_requests_total.labels(
            request.method, path, str(response.status_code),
        ).inc()
        telemetry.api_request_duration_seconds.labels(
            request.method, path,
        ).observe(time.perf_counter() - start)
        return response
