"""Session CRUD + message dispatch routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from legion.api.deps import get_dispatch_service, get_session_repo
from legion.api.schemas import SessionCreate, SessionMessage
from legion.domain.job import Job, JobType
from legion.domain.session import Session, SessionStatus
from legion.services.dispatch_service import DispatchService
from legion.services.session_repository import SessionRepository

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    session_repo: SessionRepository = Depends(get_session_repo),
) -> Session:
    session = Session(
        org_id=body.org_id,
        agent_group_id=body.agent_group_id,
    )
    session_repo.save(session)
    return session


@router.get("/")
def list_sessions(
    agent_group_id: str,
    session_repo: SessionRepository = Depends(get_session_repo),
) -> list[Session]:
    return session_repo.list_active(agent_group_id)


@router.get("/{session_id}")
def get_session(
    session_id: str,
    session_repo: SessionRepository = Depends(get_session_repo),
) -> Session:
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/{session_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    session_id: str,
    body: SessionMessage,
    request: Request,
    session_repo: SessionRepository = Depends(get_session_repo),
    dispatch_service: DispatchService = Depends(get_dispatch_service),
) -> Job:
    session = session_repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=422, detail="Session is not active")

    job = dispatch_service.create_job(
        session.org_id, session.agent_group_id, JobType.QUERY, body.payload,
    )
    dispatched = dispatch_service.dispatch_pending(session.agent_group_id)

    connection_manager = request.app.state.connection_manager
    for d_job, d_agent in dispatched:
        await connection_manager.send_job_to_agent(d_job, d_agent)

    return job
