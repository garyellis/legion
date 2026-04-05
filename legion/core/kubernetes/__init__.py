"""Framework-free Kubernetes inspection tools for Legion."""

from __future__ import annotations

from legion.core.kubernetes.cluster import list_namespaces
from legion.core.kubernetes.pods import pod_logs, pod_status
from legion.core.kubernetes.resources import describe_resource, get_events

__all__ = [
    "describe_resource",
    "get_events",
    "list_namespaces",
    "pod_logs",
    "pod_status",
]
