"""Health and readiness probe endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from legion.api.deps import get_fleet_repo
from legion.services.fleet_repository import FleetRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Always returns 200."""
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
) -> JSONResponse:
    """Readiness probe. Returns 200 if the database is reachable, 503 otherwise."""
    try:
        fleet_repo.list_orgs()
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception:
        logger.warning("Readiness check failed", exc_info=True)
        return JSONResponse(status_code=503, content={"detail": "not ready"})
