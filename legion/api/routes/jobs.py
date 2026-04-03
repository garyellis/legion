"""Job read-only routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from legion.api.deps import get_job_repo
from legion.domain.job import Job
from legion.services.job_repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/")
def list_jobs(
    agent_group_id: str,
    job_repo: JobRepository = Depends(get_job_repo),
) -> list[Job]:
    return job_repo.list_active(agent_group_id)


@router.get("/{job_id}")
def get_job(
    job_id: str,
    job_repo: JobRepository = Depends(get_job_repo),
) -> Job:
    job = job_repo.get_by_id(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
