#!/usr/bin/env python3
"""Create fleet resources and send a job via the REST API."""

import time

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=5)

    # 1. Organization
    org = c.post("/organizations/", json={"name": "Acme", "slug": "acme"}).json()
    print(f"Org created:          {org['id']}  ({org['name']})")

    # 2. ClusterGroup
    cg = c.post("/cluster-groups/", json={
        "org_id": org["id"], "name": "Production", "slug": "prod",
        "environment": "prod", "provider": "eks",
    }).json()
    print(f"ClusterGroup created: {cg['id']}  ({cg['name']})")

    # 3. ChannelMapping (optional but shows CRUD)
    cm = c.post("/channel-mappings/", json={
        "org_id": org["id"], "channel_id": "C-DEMO", "cluster_group_id": cg["id"],
    }).json()
    print(f"ChannelMapping:       {cm['id']}  (channel={cm['channel_id']})")

    # 4. FilterRule
    fr = c.post("/filter-rules/", json={
        "channel_mapping_id": cm["id"], "pattern": "ERROR.*OOM",
    }).json()
    print(f"FilterRule:           {fr['id']}  (pattern={fr['pattern']})")

    # 5. PromptConfig
    pc = c.put(f"/prompt-configs/{cg['id']}", json={
        "system_prompt": "You are an SRE expert.", "persona": "K8s Guru",
    }).json()
    print(f"PromptConfig:         {pc['id']}  (persona={pc['persona']})")

    # 6. Check agents
    agents = c.get(f"/agents/?cluster_group_id={cg['id']}").json()
    print(f"\nAgents in cluster group: {len(agents)}")
    if not agents:
        print("  (none yet — start demo_agent.py in another terminal)")

    # 7. Session + message
    session = c.post("/sessions/", json={
        "org_id": org["id"], "cluster_group_id": cg["id"],
    }).json()
    print(f"\nSession created:      {session['id']}")

    print("Sending message: 'What pods are in CrashLoopBackOff?'")
    job = c.post(f"/sessions/{session['id']}/messages", json={
        "payload": "What pods are in CrashLoopBackOff?",
    }).json()
    print(f"Job created:          {job['id']}  status={job['status']}")

    # 8. Poll job status
    print("\nPolling job status...")
    for _ in range(10):
        time.sleep(1)
        j = c.get(f"/jobs/{job['id']}").json()
        print(f"  status={j['status']}", end="")
        if j.get("result"):
            print(f"  result={j['result']}")
            break
        elif j.get("error"):
            print(f"  error={j['error']}")
            break
        else:
            print()
    else:
        print("  (timed out — is an agent connected?)")


if __name__ == "__main__":
    main()
