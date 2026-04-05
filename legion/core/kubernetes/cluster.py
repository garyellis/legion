"""Cluster-level Kubernetes tools."""

from __future__ import annotations

from legion.core.kubernetes.client import (
    get_core_v1_api,
    handle_kubernetes_api_error,
)
from legion.plumbing.plugins import tool


@tool(
    "list_namespaces",
    description="List namespaces in the cluster.",
    category="kubernetes",
    read_only=True,
)
def list_namespaces() -> str:
    """Return namespace names and phases sorted by name."""
    api = get_core_v1_api()
    try:
        response = api.list_namespace()
    except Exception as exc:
        return handle_kubernetes_api_error(
            exc,
            forbidden_action="Access denied listing namespaces",
            unexpected_action="listing namespaces",
        )

    namespaces = sorted(getattr(response, "items", []), key=lambda item: getattr(getattr(item, "metadata", None), "name", ""))
    if not namespaces:
        return "No namespaces found in the cluster."

    lines = ["Namespaces in the cluster:"]
    for item in namespaces:
        name = getattr(getattr(item, "metadata", None), "name", "<unknown>")
        phase = getattr(getattr(item, "status", None), "phase", "Unknown")
        lines.append(f"- {name}: phase={phase}")
    return "\n".join(lines)
