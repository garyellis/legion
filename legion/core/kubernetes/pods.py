"""Pod-oriented Kubernetes tools."""

from __future__ import annotations

from typing import Any

from legion.core.kubernetes.client import (
    get_core_v1_api,
    handle_kubernetes_api_error,
)
from legion.plumbing.plugins import tool

MAX_POD_LOG_OUTPUT_CHARS = 16_000
_TRUNCATION_MARKER = "\n...[truncated]"


@tool(
    "pod_status",
    description="Get pod status in a namespace.",
    category="kubernetes",
    read_only=True,
)
def pod_status(namespace: str = "default") -> str:
    """Return a readable summary of pod status in a namespace."""
    api = get_core_v1_api()
    try:
        response = api.list_namespaced_pod(namespace)
    except Exception as exc:
        return handle_kubernetes_api_error(
            exc,
            missing_message=f"Namespace {namespace} not found.",
            forbidden_action="Access denied listing pods",
            unexpected_action="listing pods",
            namespace=namespace,
        )

    pods = sorted(getattr(response, "items", []), key=lambda pod: _pod_name(pod))
    if not pods:
        return f"No pods found in namespace {namespace}."

    lines = [f"Pods in namespace {namespace}:"]
    for pod in pods:
        phase = getattr(getattr(pod, "status", None), "phase", "Unknown")
        ready, total = _ready_counts(pod)
        restarts = _restart_count(pod)
        node_name = getattr(getattr(pod, "spec", None), "node_name", None) or "<unknown>"
        lines.append(
            f"- {_pod_name(pod)}: phase={phase}, ready={ready}/{total}, restarts={restarts}, node={node_name}"
        )
    return "\n".join(lines)


@tool(
    "pod_logs",
    description="Fetch recent logs from a pod.",
    category="kubernetes",
    read_only=True,
)
def pod_logs(namespace: str, pod_name: str, tail_lines: int = 100) -> str:
    """Return recent pod logs with a deterministic header."""
    api = get_core_v1_api()
    try:
        logs = api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
        )
    except Exception as exc:
        return handle_kubernetes_api_error(
            exc,
            not_found_message=f"Pod {pod_name} not found in namespace {namespace}.",
            forbidden_action="Access denied reading logs for pod",
            unexpected_action=f"reading logs for pod {pod_name}",
            namespace=namespace,
            name=pod_name,
        )

    body = logs.rstrip("\n") if isinstance(logs, str) else str(logs)
    if not body:
        body = "<no logs>"
    body = _truncate_log_output(body)
    return f"Logs for pod {pod_name} in namespace {namespace} (tail_lines={tail_lines}):\n{body}"


def _truncate_log_output(body: str) -> str:
    if len(body) <= MAX_POD_LOG_OUTPUT_CHARS:
        return body
    limit = MAX_POD_LOG_OUTPUT_CHARS - len(_TRUNCATION_MARKER)
    if limit <= 0:
        return _TRUNCATION_MARKER[:MAX_POD_LOG_OUTPUT_CHARS]
    return f"{body[:limit]}{_TRUNCATION_MARKER}"


def _pod_name(pod: Any) -> str:
    metadata = getattr(pod, "metadata", None)
    return getattr(metadata, "name", "<unknown>")


def _ready_counts(pod: Any) -> tuple[int, int]:
    container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
    total = len(container_statuses)
    ready = sum(1 for container_status in container_statuses if getattr(container_status, "ready", False))
    return ready, total


def _restart_count(pod: Any) -> int:
    container_statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
    return sum(int(getattr(status, "restart_count", 0) or 0) for status in container_statuses)
