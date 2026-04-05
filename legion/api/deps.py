"""FastAPI dependency injection — Depends() accessors reading from app.state."""

from __future__ import annotations

from fastapi import Request

from legion.services.agent_delivery_service import AgentDeliveryService
from legion.services.dispatch_service import DispatchService
from legion.services.agent_session_repository import AgentSessionRepository
from legion.services.filter_service import FilterService
from legion.services.fleet_repository import FleetRepository
from legion.services.job_repository import JobRepository
from legion.services.session_repository import SessionRepository
from legion.services.session_service import SessionService


def get_fleet_repo(request: Request) -> FleetRepository:
    return request.app.state.fleet_repo


def get_job_repo(request: Request) -> JobRepository:
    return request.app.state.job_repo


def get_session_repo(request: Request) -> SessionRepository:
    return request.app.state.session_repo


def get_dispatch_service(request: Request) -> DispatchService:
    return request.app.state.dispatch_service


def get_agent_delivery_service(request: Request) -> AgentDeliveryService:
    return request.app.state.agent_delivery_service


def get_agent_session_repo(request: Request) -> AgentSessionRepository:
    return request.app.state.agent_session_repo


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_filter_service(request: Request) -> FilterService:
    return request.app.state.filter_service
