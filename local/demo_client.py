#!/usr/bin/env python3
"""Ensure demo fleet resources exist and send a job via the REST API."""

from __future__ import annotations

import os
import time

import httpx

_DEMO_ORG_NAME = "Demo"
_DEMO_ORG_SLUG = "demo"
_DEMO_PROJECT_NAME = "Demo"
_DEMO_PROJECT_SLUG = "demo"
_DEMO_AGENT_GROUP_NAME = "Demo Agents"
_DEMO_AGENT_GROUP_SLUG = "demo"


def _base_url() -> str:
    return os.environ.get("LEGION_API_URL", "http://127.0.0.1:8000")


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

    response = client.post("/organizations/", json={"name": _DEMO_ORG_NAME, "slug": _DEMO_ORG_SLUG})
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


def main() -> None:
    client = httpx.Client(base_url=_base_url(), timeout=5.0, headers=_headers())

    org = _ensure_org(client)
    print(f"Org ready:            {org['id']}  ({org['name']})")

    project = _ensure_project(client, org["id"])
    print(f"Project ready:        {project['id']}  ({project['name']})")

    agent_group = _ensure_agent_group(client, org["id"], project["id"])
    print(f"AgentGroup ready:     {agent_group['id']}  ({agent_group['name']})")

    prompt_config = client.put(f"/prompt-configs/{agent_group['id']}", json={
        "system_prompt": "You are an SRE expert.",
        "persona": "K8s Guru",
    })
    prompt_config.raise_for_status()
    prompt_config_body = prompt_config.json()
    print(f"PromptConfig:         {prompt_config_body['id']}  (persona={prompt_config_body['persona']})")

    agents = client.get("/agents/", params={"agent_group_id": agent_group["id"]})
    agents.raise_for_status()
    agents_body = agents.json()
    print(f"\nAgents in agent group: {len(agents_body)}")
    if not agents_body:
        print("  (none yet — start demo_agent.py or docker compose --profile demo up)")

    session = client.post("/sessions/", json={
        "org_id": org["id"],
        "agent_group_id": agent_group["id"],
    })
    session.raise_for_status()
    session_body = session.json()
    print(f"\nSession created:      {session_body['id']}")

    print("Sending message: 'What pods are in CrashLoopBackOff?'")
    job = client.post(f"/sessions/{session_body['id']}/messages", json={
        "payload": "What pods are in CrashLoopBackOff?",
    })
    job.raise_for_status()
    job_body = job.json()
    print(f"Job created:          {job_body['id']}  status={job_body['status']}")

    print("\nPolling job status...")
    for _ in range(10):
        time.sleep(1)
        response = client.get(f"/jobs/{job_body['id']}")
        response.raise_for_status()
        job_status = response.json()
        print(f"  status={job_status['status']}", end="")
        if job_status.get("result"):
            print(f"  result={job_status['result']}")
            break
        if job_status.get("error"):
            print(f"  error={job_status['error']}")
            break
        print()
    else:
        print("  (timed out — is a demo agent connected?)")


if __name__ == "__main__":
    main()
