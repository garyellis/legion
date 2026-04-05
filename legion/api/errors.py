"""Map service exceptions to HTTP status codes."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from legion.services.exceptions import (
    AgentGroupNotFoundError,
    AgentNotFoundError,
    DispatchError,
    DuplicateError,
    FilterError,
    InvalidRegistrationTokenError,
    InvalidSessionTokenError,
    ServiceError,
    SessionError,
    SessionTokenMismatchError,
)


def register_error_handlers(app: FastAPI) -> None:
    """Register exception handlers on the FastAPI app."""

    @app.exception_handler(AgentNotFoundError)
    async def _agent_not_found(request: Request, exc: AgentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(AgentGroupNotFoundError)
    async def _agent_group_not_found(request: Request, exc: AgentGroupNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(InvalidRegistrationTokenError)
    async def _invalid_registration_token(
        request: Request,
        exc: InvalidRegistrationTokenError,
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    @app.exception_handler(InvalidSessionTokenError)
    async def _invalid_session_token(request: Request, exc: InvalidSessionTokenError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": exc.message})

    @app.exception_handler(SessionTokenMismatchError)
    async def _session_token_mismatch(
        request: Request,
        exc: SessionTokenMismatchError,
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": exc.message})

    @app.exception_handler(SessionError)
    async def _session_error(request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(DispatchError)
    async def _dispatch_error(request: Request, exc: DispatchError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(DuplicateError)
    async def _duplicate(request: Request, exc: DuplicateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": exc.message})

    @app.exception_handler(FilterError)
    async def _filter_error(request: Request, exc: FilterError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": exc.message})

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": exc.message})
