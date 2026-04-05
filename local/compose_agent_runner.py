#!/usr/bin/env python3
"""Bootstrap demo control-plane resources, then exec the real agent runner."""

from __future__ import annotations

import os
from os import execvpe

import httpx

_DEMO_ORG_NAME = "Demo"
_DEMO_ORG_SLUG = "demo"
_DEMO_PROJECT_NAME = "Demo"
_DEMO_PROJECT_SLUG = "demo"
_DEMO_AGENT_GROUP_NAME = "Demo Agents"
_DEMO_AGENT_GROUP_SLUG = "demo"


def _base_url() -> str:
    return os.environ.get("LEGION_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers() -> dict[str, str]:
    api_key = os.environ.get("LEGION_API_KEY", "")
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def _ensure_org(client: httpx.Client) -> dict[str, object]:
    response = client.get("/organizations/")
    response.raise_for_status()
    for org in response.json():
        if org["slug"] == _DEMO_ORG_SLUG:
            return org

    response = client.post(
        "/organizations/",
        json={"name": _DEMO_ORG_NAME, "slug": _DEMO_ORG_SLUG},
    )
    response.raise_for_status()
    return response.json()


def _ensure_project(client: httpx.Client, org_id: str) -> dict[str, object]:
    response = client.get("/projects/", params={"org_id": org_id})
    response.raise_for_status()
    for project in response.json():
        if project["slug"] == _DEMO_PROJECT_SLUG:
            return project

    response = client.post(
        "/projects/",
        json={"org_id": org_id, "name": _DEMO_PROJECT_NAME, "slug": _DEMO_PROJECT_SLUG},
    )
    response.raise_for_status()
    return response.json()


def _ensure_agent_group(client: httpx.Client, org_id: str, project_id: str) -> dict[str, object]:
    response = client.get("/agent-groups/", params={"project_id": project_id})
    response.raise_for_status()
    for group in response.json():
        if group["slug"] == _DEMO_AGENT_GROUP_SLUG:
            return group

    response = client.post(
        "/agent-groups/",
        json={
            "org_id": org_id,
            "project_id": project_id,
            "name": _DEMO_AGENT_GROUP_NAME,
            "slug": _DEMO_AGENT_GROUP_SLUG,
            "environment": "dev",
            "provider": "on-prem",
        },
    )
    response.raise_for_status()
    return response.json()


def _rotate_registration_token(client: httpx.Client, agent_group_id: str) -> str:
    response = client.post(f"/agent-groups/{agent_group_id}/token")
    response.raise_for_status()
    return response.json()["registration_token"]


def main() -> None:
    api_url = _base_url()
    agent_name = os.environ.get("LEGION_AGENT_NAME", "demo-agent-1")

    with httpx.Client(base_url=api_url, timeout=5.0, headers=_headers()) as client:
        org = _ensure_org(client)
        project = _ensure_project(client, org["id"])
        agent_group = _ensure_agent_group(client, org["id"], project["id"])
        registration_token = _rotate_registration_token(client, agent_group["id"])

    env = os.environ.copy()
    env["AGENT_RUNNER_API_URL"] = api_url
    env["AGENT_RUNNER_REGISTRATION_TOKEN"] = registration_token
    env["AGENT_RUNNER_AGENT_NAME"] = agent_name

    execvpe("legion-agent", ["legion-agent"], env)


if __name__ == "__main__":
    main()
