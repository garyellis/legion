"""FastAPI app factory, lifespan wiring, and entry point."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
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
    metrics,
    organizations,
    projects,
    prompt_configs,
    sessions,
)
from legion.api.websocket import ConnectionManager, router as ws_router
from legion.plumbing.config.database import DatabaseConfig
from legion.plumbing.database import create_engine
from legion.plumbing.migrations import validate_database_schema_current
from legion.plumbing.logging import LogFormat, LogOutput, setup_logging
from legion.services.agent_delivery_service import AgentDeliveryService
from legion.services.agent_session_repository import AgentSessionRepository
from legion.services.agent_session_repository import SQLiteAgentSessionRepository
from legion.services.audit_event_repository import SQLiteAuditEventRepository
from legion.services.audit_service import AuditService
from legion.services.message_repository import SQLiteMessageRepository
from legion.services.message_service import MessageService
from legion.services.dispatch_service import DispatchService
from legion.services.filter_service import FilterService
from legion.services.fleet_repository import FleetRepository
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.services.job_repository import JobRepository
from legion.services.job_repository import SQLiteJobRepository
from legion.services.session_repository import SessionRepository
from legion.services.session_repository import SQLiteSessionRepository
from legion.services.session_service import SessionService

logger = logging.getLogger(__name__)

# Well-known IDs for the default org and project.
_DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


def _seed_defaults(fleet_repo: FleetRepository) -> None:
    """Ensure the 'default' organization and project always exist."""
    from legion.domain.organization import Organization
    from legion.domain.project import Project

    if fleet_repo.get_org(_DEFAULT_ORG_ID) is None:
        fleet_repo.save_org(Organization(
            id=_DEFAULT_ORG_ID, name="default", slug="default",
        ))
        logger.info("Seeded default organization")

    if fleet_repo.get_project(_DEFAULT_PROJECT_ID) is None:
        fleet_repo.save_project(Project(
            id=_DEFAULT_PROJECT_ID, org_id=_DEFAULT_ORG_ID,
            name="default", slug="default",
        ))
        logger.info("Seeded default project")


def create_app(
    *,
    fleet_repo: FleetRepository | None = None,
    job_repo: JobRepository | None = None,
    session_repo: SessionRepository | None = None,
    agent_session_repo: AgentSessionRepository | None = None,
    api_config: APIConfig | None = None,
    api_key: str = "",
) -> FastAPI:
    """App factory. Pass repos for testing; defaults to SQLite."""

    resolved_api_config = api_config or APIConfig(api_key=api_key)

    provided_repos = (fleet_repo, job_repo, session_repo, agent_session_repo)
    if any(repo is not None for repo in provided_repos) and not all(
        repo is not None for repo in provided_repos
    ):
        raise ValueError(
            "fleet_repo, job_repo, session_repo, and agent_session_repo must all be provided together",
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.api_config = resolved_api_config
        # Repos — use provided or create defaults
        if fleet_repo is not None:
            app.state.fleet_repo = fleet_repo
            app.state.job_repo = job_repo
            app.state.session_repo = session_repo
            app.state.agent_session_repo = agent_session_repo
        else:
            db_config = DatabaseConfig()
            engine = create_engine(
                db_config.url, echo=db_config.echo, pool_pre_ping=db_config.pool_pre_ping,
            )
            validate_database_schema_current(engine)

            app.state.fleet_repo = SQLiteFleetRepository(engine)
            app.state.job_repo = SQLiteJobRepository(engine)
            app.state.session_repo = SQLiteSessionRepository(engine)
            app.state.agent_session_repo = SQLiteAgentSessionRepository(engine)
            app.state.message_service = MessageService(SQLiteMessageRepository(engine))
            app.state.audit_service = AuditService(SQLiteAuditEventRepository(engine))

        _seed_defaults(app.state.fleet_repo)

        # Services
        app.state.dispatch_service = DispatchService(
            app.state.fleet_repo,
            app.state.job_repo,
            app.state.session_repo,
            app.state.agent_session_repo,
            agent_session_token_ttl_seconds=resolved_api_config.agent_session_token_ttl_seconds,
        )
        app.state.session_service = SessionService(
            app.state.session_repo, app.state.fleet_repo,
        )
        app.state.filter_service = FilterService()
        app.state.connection_manager = ConnectionManager()
        app.state.agent_delivery_service = AgentDeliveryService(
            app.state.dispatch_service,
            app.state.fleet_repo,
        )

        app.state.db_executor = ThreadPoolExecutor(max_workers=4)

        logger.info("API started")
        yield

        # Cleanup
        audit_service = getattr(app.state, "audit_service", None)
        if audit_service is not None:
            audit_service.close()
        app.state.db_executor.shutdown(wait=False)
        await app.state.connection_manager.disconnect_all()
        logger.info("API stopped")

    app = FastAPI(title="Legion API", lifespan=lifespan)

    if resolved_api_config.api_key:
        from legion.api.middleware import APIKeyMiddleware

        app.add_middleware(APIKeyMiddleware, api_key=resolved_api_config.api_key)

    from legion.api.middleware import RequestMetricsMiddleware

    app.add_middleware(RequestMetricsMiddleware)

    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(organizations.router)
    app.include_router(projects.router)
    app.include_router(agent_groups.router)
    app.include_router(agents.router)
    app.include_router(channel_mappings.router)
    app.include_router(filter_rules.router)
    app.include_router(prompt_configs.router)
    app.include_router(jobs.router)
    app.include_router(sessions.router)
    app.include_router(metrics.router)
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
    app = create_app(api_config=api_config)
    uvicorn.run(app, host=api_config.host, port=api_config.port)


if __name__ == "__main__":
    main()
