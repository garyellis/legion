"""API middleware for authentication and request processing."""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


_PUBLIC_PATHS = frozenset({"/health", "/health/ready", "/docs", "/openapi.json"})
_PUBLIC_PREFIXES = ("/ws/",)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header on non-public routes.

    If *api_key* is empty, all requests pass through (dev mode).
    """

    def __init__(self, app: ASGIApp, *, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        if self._api_key:
            path = request.url.path
            if path not in _PUBLIC_PATHS and not path.startswith(_PUBLIC_PREFIXES):
                provided = request.headers.get("X-API-Key", "")
                if provided != self._api_key:
                    return Response(
                        content=json.dumps({"detail": "Invalid or missing API key"}),
                        status_code=401,
                        media_type="application/json",
                    )

        return await call_next(request)
