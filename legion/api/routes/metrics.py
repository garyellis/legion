"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from legion.plumbing import telemetry

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    """Return Prometheus exposition when available."""
    if not telemetry.metrics_available():
        return JSONResponse(
            status_code=501,
            content={"detail": "prometheus_client is not installed"},
        )

    payload, content_type = telemetry.render_metrics()
    return Response(content=payload, media_type=content_type)
