#!/usr/bin/env python3
"""Pretend agent that registers first, then connects via WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets

_DEMO_ORG_NAME = "Demo"
_DEMO_ORG_SLUG = "demo"
_DEMO_PROJECT_NAME = "Demo"
_DEMO_PROJECT_SLUG = "demo"
_DEMO_AGENT_GROUP_NAME = "Demo Agents"
_DEMO_AGENT_GROUP_SLUG = "demo"


def _build_headers() -> dict[str, str]:
    api_key = os.environ.get("LEGION_API_KEY", "")
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def _normalize_control_plane_urls(raw_base_url: str) -> tuple[str, str]:
    parts = urlsplit(raw_base_url.rstrip("/"))
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"LEGION_API_URL must be a full URL, got {raw_base_url!r}")

    rest_scheme = {"ws": "http", "wss": "https"}.get(parts.scheme, parts.scheme)
    if rest_scheme not in {"http", "https"}:
        raise ValueError(f"LEGION_API_URL must use http(s) or ws(s), got {raw_base_url!r}")

    rest_base = urlunsplit((rest_scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    websocket_scheme = "wss" if rest_scheme == "https" else "ws"
    websocket_base = urlunsplit((websocket_scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    return rest_base, websocket_base


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


def _register_agent(client: httpx.Client, agent_id: str) -> tuple[str, str, int]:
    org = _ensure_org(client)
    project = _ensure_project(client, org["id"])
    agent_group = _ensure_agent_group(client, org["id"], project["id"])

    response = client.post(f"/agent-groups/{agent_group['id']}/token")
    response.raise_for_status()
    registration_token = response.json()["registration_token"]

    response = client.post(
        "/agents/register",
        json={
            "registration_token": registration_token,
            "name": agent_id,
            "capabilities": [],
        },
    )
    response.raise_for_status()
    payload = response.json()
    return (
        payload["session_token"],
        payload["config"]["websocket_path"],
        payload["config"]["heartbeat_interval_seconds"],
    )


async def main(agent_id: str, base_url: str | None = None) -> None:
    raw_base_url = base_url or os.environ.get("LEGION_API_URL", "http://127.0.0.1:8000")
    api_base_url, websocket_base_url = _normalize_control_plane_urls(raw_base_url)

    with httpx.Client(base_url=api_base_url, timeout=5.0, headers=_build_headers()) as client:
        session_token, websocket_path, heartbeat_interval = _register_agent(client, agent_id)

    websocket_uri = f"{websocket_base_url}{websocket_path}"
    print(f"Connecting to {websocket_uri} ...")

    async with websockets.connect(
        websocket_uri,
        additional_headers={"Authorization": f"Bearer {session_token}"},
    ) as ws:
        print(f"Agent '{agent_id}' connected. Waiting for jobs...")

        async def heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(heartbeat_interval)
                await ws.send(json.dumps({"type": "heartbeat"}))
                print("  [heartbeat sent]")

        heartbeat_task = asyncio.create_task(heartbeat_loop())

        try:
            async for raw in ws:
                msg = json.loads(raw)
                print(f"  Received: {msg}")

                if msg.get("type") == "job_dispatch":
                    job_id = msg["job_id"]
                    payload = msg.get("payload", "")

                    await ws.send(json.dumps({"type": "job_started", "job_id": job_id}))
                    print(f"  [job_started] {job_id}")

                    await asyncio.sleep(1)

                    result = f"Agent '{agent_id}' handled: {payload}"
                    await ws.send(json.dumps({
                        "type": "job_result",
                        "job_id": job_id,
                        "result": result,
                    }))
                    print(f"  [job_result]  {job_id} -> {result}")
        finally:
            heartbeat_task.cancel()


if __name__ == "__main__":
    agent_id = sys.argv[1] if len(sys.argv) > 1 else "demo-agent-1"
    try:
        asyncio.run(main(agent_id))
    except KeyboardInterrupt:
        print("\nAgent disconnected.")
