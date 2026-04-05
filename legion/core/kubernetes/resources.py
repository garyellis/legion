"""General Kubernetes resource inspection tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from legion.core.kubernetes.client import (
    get_core_v1_api,
    handle_kubernetes_api_error,
    resource_to_dict,
)
from legion.plumbing.plugins import tool


@dataclass(frozen=True)
class _ResourceHandler:
    kind_label: str
    fetch: Callable[[Any, str, str], Any]
    namespaced: bool


@tool(
    "describe_resource",
    description="Describe a core Kubernetes resource.",
    category="kubernetes",
    read_only=True,
)
def describe_resource(kind: str, name: str, namespace: str = "default") -> str:
    api = get_core_v1_api()
    normalized_kind = _normalize_kind(kind)
    handler = _RESOURCE_HANDLERS.get(normalized_kind)
    if handler is None:
        supported = ", ".join(sorted(_RESOURCE_HANDLERS))
        return f"Unsupported resource kind '{kind}'. Supported kinds: {supported}."

    try:
        resource = handler.fetch(api, name, namespace)
    except Exception as exc:
        scope = f" in namespace {namespace}" if handler.namespaced else ""
        return handle_kubernetes_api_error(
            exc,
            forbidden_action=f"Access denied describing {handler.kind_label.lower()}",
            unexpected_action=f"describing {handler.kind_label.lower()} {name}",
            namespace=namespace if handler.namespaced else None,
            name=name,
            not_found_message=f"{handler.kind_label} {name} not found{scope}.",
        )

    return _format_resource_description(handler.kind_label, resource, namespace if handler.namespaced else None)


@tool(
    "get_events",
    description="Get recent events in a namespace.",
    category="kubernetes",
    read_only=True,
)
def get_events(namespace: str = "default", limit: int = 50) -> str:
    """Return recent namespace events sorted newest-first."""
    api = get_core_v1_api()
    try:
        response = api.list_namespaced_event(namespace=namespace, limit=limit)
    except Exception as exc:
        return handle_kubernetes_api_error(
            exc,
            forbidden_action="Access denied listing events",
            unexpected_action="listing events",
            namespace=namespace,
            not_found_message=f"Namespace {namespace} not found.",
        )

    items = sorted(
        getattr(response, "items", []),
        key=_event_sort_key,
        reverse=True,
    )[:limit]
    if not items:
        return f"No events found in namespace {namespace}."

    lines = [f"Recent events in namespace {namespace}:"]
    for event in items:
        lines.append(_format_event_line(event))
    return "\n".join(lines)


def _normalize_kind(kind: str) -> str:
    normalized = kind.strip().lower()
    aliases = {
        "pods": "pod",
        "services": "service",
        "svc": "service",
        "configmaps": "configmap",
        "secrets": "secret",
        "namespaces": "namespace",
        "nodes": "node",
        "persistentvolumeclaims": "persistentvolumeclaim",
        "pvc": "persistentvolumeclaim",
        "pvcs": "persistentvolumeclaim",
    }
    return aliases.get(normalized, normalized)


def _format_resource_description(kind_label: str, resource: Any, namespace: str | None) -> str:
    data = resource_to_dict(resource)
    metadata = data.get("metadata", {})
    lines = [
        f"Kind: {kind_label}",
        f"Name: {metadata.get('name', '<unknown>')}",
    ]
    if namespace is not None:
        lines.append(f"Namespace: {metadata.get('namespace', namespace)}")
    lines.extend(
        [
            f"Labels: {_format_key_value_pairs(metadata.get('labels'))}",
            f"Annotations: {_format_key_value_pairs(metadata.get('annotations'))}",
            f"Created At: {metadata.get('creation_timestamp') or '<unknown>'}",
            "Details:",
            json.dumps(_resource_details(kind_label, data), indent=2, sort_keys=True, default=str),
        ]
    )
    return "\n".join(lines)


def _resource_details(kind_label: str, data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status") or {}
    spec = data.get("spec") or {}
    details: dict[str, Any] = {}

    if kind_label == "Pod":
        details["phase"] = status.get("phase")
        details["pod_ip"] = status.get("pod_ip")
        details["host_ip"] = status.get("host_ip")
        details["node_name"] = spec.get("node_name")
    elif kind_label == "Service":
        details["type"] = spec.get("type")
        details["cluster_ip"] = spec.get("cluster_ip")
        details["ports"] = spec.get("ports")
        details["selector"] = spec.get("selector")
    elif kind_label == "ConfigMap":
        details["data_keys"] = sorted((data.get("data") or {}).keys())
        details["binary_data_keys"] = sorted((data.get("binary_data") or {}).keys())
    elif kind_label == "Secret":
        details["type"] = data.get("type")
        details["data_keys"] = sorted((data.get("data") or {}).keys())
        details["string_data_keys"] = sorted((data.get("string_data") or {}).keys())
    elif kind_label == "Namespace":
        details["phase"] = status.get("phase")
    elif kind_label == "Node":
        details["taints"] = spec.get("taints")
        details["conditions"] = status.get("conditions")
        details["addresses"] = status.get("addresses")
    elif kind_label == "PersistentVolumeClaim":
        details["phase"] = status.get("phase")
        details["access_modes"] = status.get("access_modes") or spec.get("access_modes")
        details["storage_class_name"] = spec.get("storage_class_name")
        details["volume_name"] = spec.get("volume_name")

    return {key: value for key, value in details.items() if value not in (None, [], {}, "")}


def _format_key_value_pairs(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return "<none>"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _event_sort_key(event: Any) -> tuple[float, str]:
    timestamp = (
        getattr(event, "event_time", None)
        or getattr(event, "last_timestamp", None)
        or getattr(getattr(event, "metadata", None), "creation_timestamp", None)
    )
    if not isinstance(timestamp, datetime):
        normalized_timestamp = float("-inf")
    else:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        normalized_timestamp = timestamp.astimezone(timezone.utc).timestamp()
    name = getattr(getattr(event, "metadata", None), "name", "")
    return normalized_timestamp, name


def _format_event_line(event: Any) -> str:
    timestamp = (
        getattr(event, "event_time", None)
        or getattr(event, "last_timestamp", None)
        or getattr(getattr(event, "metadata", None), "creation_timestamp", None)
    )
    timestamp_text = timestamp.isoformat() if isinstance(timestamp, datetime) else "<unknown>"
    involved_object = getattr(event, "involved_object", None)
    object_kind = getattr(involved_object, "kind", "Resource")
    object_name = getattr(involved_object, "name", "<unknown>")
    event_type = getattr(event, "type", "Normal")
    reason = getattr(event, "reason", "<unknown>")
    message = getattr(event, "message", "")
    return f"- {timestamp_text} {event_type} {reason} {object_kind}/{object_name}: {message}".rstrip()


_RESOURCE_HANDLERS: dict[str, _ResourceHandler] = {
    "configmap": _ResourceHandler(
        kind_label="ConfigMap",
        fetch=lambda api, name, namespace: api.read_namespaced_config_map(name=name, namespace=namespace),
        namespaced=True,
    ),
    "namespace": _ResourceHandler(
        kind_label="Namespace",
        fetch=lambda api, name, _namespace: api.read_namespace(name=name),
        namespaced=False,
    ),
    "node": _ResourceHandler(
        kind_label="Node",
        fetch=lambda api, name, _namespace: api.read_node(name=name),
        namespaced=False,
    ),
    "persistentvolumeclaim": _ResourceHandler(
        kind_label="PersistentVolumeClaim",
        fetch=lambda api, name, namespace: api.read_namespaced_persistent_volume_claim(name=name, namespace=namespace),
        namespaced=True,
    ),
    "pod": _ResourceHandler(
        kind_label="Pod",
        fetch=lambda api, name, namespace: api.read_namespaced_pod(name=name, namespace=namespace),
        namespaced=True,
    ),
    "secret": _ResourceHandler(
        kind_label="Secret",
        fetch=lambda api, name, namespace: api.read_namespaced_secret(name=name, namespace=namespace),
        namespaced=True,
    ),
    "service": _ResourceHandler(
        kind_label="Service",
        fetch=lambda api, name, namespace: api.read_namespaced_service(name=name, namespace=namespace),
        namespaced=True,
    ),
}
