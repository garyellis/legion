"""Job read-only routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from legion.api.deps import get_job_repo, get_pagination
from legion.api.schemas.jobs import JobResponse
from legion.api.schemas.pagination import PaginatedResponse, PaginationParams
from legion.services.job_repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/")
def list_jobs(
    agent_group_id: str,
    job_repo: JobRepository = Depends(get_job_repo),
    pagination: PaginationParams = Depends(get_pagination),
) -> PaginatedResponse[JobResponse]:
    jobs = job_repo.list_active(agent_group_id)
    items = [JobResponse.from_domain(j) for j in jobs[pagination.offset:pagination.offset + pagination.limit]]
    return PaginatedResponse(items=items, total=len(jobs), limit=pagination.limit, offset=pagination.offset)


@router.get("/{job_id}")
def get_job(
    job_id: str,
    job_repo: JobRepository = Depends(get_job_repo),
) -> JobResponse:
    job = job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.from_domain(job)
