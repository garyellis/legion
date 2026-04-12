"""Session CRUD + message dispatch routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from legion.api.deps import (
    get_agent_delivery_service,
    get_dispatch_service,
    get_fleet_repo,
    get_pagination,
    get_session_repo,
)
from legion.api.schemas.jobs import JobResponse
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.api.schemas.sessions import SessionCreate, SessionMessage, SessionResponse
from legion.domain.job import JobType
from legion.domain.session import Session, SessionStatus
from legion.services.agent_delivery_service import AgentDeliveryService
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import FleetRepository
from legion.services.session_repository import SessionRepository

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    fleet_repo: FleetRepository = Depends(get_fleet_repo),
    session_repo: SessionRepository = Depends(get_session_repo),
) -> SessionResponse:
    if fleet_repo.get_org(body.org_id) is None:
        raise HTTPException(status_code=404, detail=f"Organization {body.org_id} not found")
    if fleet_repo.get_agent_group(body.agent_group_id) is None:
        raise HTTPException(status_code=404, detail=f"AgentGroup {body.agent_group_id} not found")
    session = Session(
        org_id=body.org_id,
        agent_group_id=body.agent_group_id,
    )
    session_repo.save(session)
    return SessionResponse.from_domain(session)


@router.get("/")
def list_sessions(
    agent_group_id: str,
    session_repo: SessionRepository = Depends(get_session_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[SessionResponse]:
    sessions = session_repo.list_active(agent_group_id)
    items = [SessionResponse.from_domain(s) for s in sessions[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(sessions), limit=pagination.limit, offset=pagination.offset)


@router.get("/{session_id}")
def get_session(
    session_id: str,
    session_repo: SessionRepository = Depends(get_session_repo),
) -> SessionResponse:
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.from_domain(session)


@router.post("/{session_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    session_id: str,
    body: SessionMessage,
    request: Request,
    session_repo: SessionRepository = Depends(get_session_repo),
    dispatch_service: DispatchService = Depends(get_dispatch_service),
    agent_delivery_service: AgentDeliveryService = Depends(get_agent_delivery_service),
) -> JobResponse:
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=422, detail="Session is not active")

    job = dispatch_service.create_job(
        session.org_id,
        session.agent_group_id,
        JobType.QUERY,
        body.payload,
        session_id=session.id,
    )
    connection_manager = request.app.state.connection_manager
    await agent_delivery_service.dispatch_pending_for_group(
        session.agent_group_id,
        connection_manager.send_job_to_agent,
    )

    return JobResponse.from_domain(job)
