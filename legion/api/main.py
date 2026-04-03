"""FastAPI app factory, lifespan wiring, and entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI

from legion.api.config import APIConfig
from legion.api.errors import register_error_handlers
from legion.api.routes import (
    agents,
    channel_mappings,
    agent_groups,
    filter_rules,
    health,
    jobs,
    organizations,
    prompt_configs,
    sessions,
)
from legion.api.websocket import ConnectionManager, router as ws_router
from legion.plumbing.logging import LogFormat, LogOutput, setup_logging
from legion.services.dispatch_service import DispatchService
from legion.services.filter_service import FilterService
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository
from legion.services.session_repository import SessionRepository
from legion.services.session_service import SessionService

logger = logging.getLogger(__name__)


def create_app(
    *,
    fleet_repo: FleetRepository | None = None,
    job_repo: JobRepository | None = None,
    session_repo: SessionRepository | None = None,
    api_key: str = "",
) -> FastAPI:
    """App factory. Pass repos for testing; defaults to SQLite."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Repos — use provided or create defaults
        if fleet_repo is not None:
            app.state.fleet_repo = fleet_repo
        else:
            from legion.plumbing.config.database import DatabaseConfig
            from legion.plumbing.database import create_all, create_engine

            db_config = DatabaseConfig()
            engine = create_engine(
                db_config.url, echo=db_config.echo, pool_pre_ping=db_config.pool_pre_ping,
            )
            create_all(engine)

            from legion.services.fleet_repository import SQLiteFleetRepository
            from legion.services.job_repository import SQLiteJobRepository
            from legion.services.session_repository import SQLiteSessionRepository

            app.state.fleet_repo = SQLiteFleetRepository(engine)
            app.state.job_repo = SQLiteJobRepository(engine)
            app.state.session_repo = SQLiteSessionRepository(engine)

        if job_repo is not None:
            app.state.job_repo = job_repo
        if session_repo is not None:
            app.state.session_repo = session_repo

        # Services
        app.state.dispatch_service = DispatchService(
            app.state.fleet_repo, app.state.job_repo,
        )
        app.state.session_service = SessionService(
            app.state.session_repo, app.state.fleet_repo,
        )
        app.state.filter_service = FilterService()
        app.state.connection_manager = ConnectionManager()

        logger.info("API started")
        yield

        # Cleanup
        await app.state.connection_manager.disconnect_all()
        logger.info("API stopped")

    app = FastAPI(title="Legion API", lifespan=lifespan)

    if api_key:
        from legion.api.middleware import APIKeyMiddleware

        app.add_middleware(APIKeyMiddleware, api_key=api_key)

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(organizations.router)
    app.include_router(agent_groups.router)
    app.include_router(agents.router)
    app.include_router(channel_mappings.router)
    app.include_router(filter_rules.router)
    app.include_router(prompt_configs.router)
    app.include_router(jobs.router)
    app.include_router(sessions.router)
    app.include_router(ws_router)

    return app


def main() -> None:
    """Entrypoint for the legion-api script."""
    api_config = APIConfig()
    setup_logging(
        level=api_config.log_level,
        output=LogOutput.STDOUT,
        fmt=LogFormat[api_config.log_format],
        quiet_loggers=["uvicorn", "uvicorn.access"],
    )
    app = create_app(api_key=api_config.api_key)
    uvicorn.run(app, host=api_config.host, port=api_config.port)


if __name__ == "__main__":
    main()
