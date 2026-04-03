#!/usr/bin/env python3
"""Pretend agent that connects via WebSocket and handles dispatched jobs."""

import asyncio
import json
import os
import sys

import websockets


async def main(agent_id: str, base_url: str | None = None) -> None:
    base_url = base_url or os.environ.get("LEGION_API_URL", "ws://127.0.0.1:8000")
    uri = f"{base_url}/ws/agents/{agent_id}"
    print(f"Connecting to {uri} ...")

    async with websockets.connect(uri) as ws:
        print(f"Agent '{agent_id}' connected. Waiting for jobs...")

        # Heartbeat task
        async def heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(10)
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

                    # Ack start
                    await ws.send(json.dumps({"type": "job_started", "job_id": job_id}))
                    print(f"  [job_started] {job_id}")

                    # Simulate work
                    await asyncio.sleep(1)

                    # Report result
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
