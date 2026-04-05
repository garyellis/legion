"""Helpers for constructing Kubernetes API clients."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from legion.core.kubernetes.exceptions import (
    KubernetesAPIError,
    KubernetesConfigError,
    KubernetesConnectionError,
)

if TYPE_CHECKING:
    from kubernetes.client import CoreV1Api


_CORE_V1_API: CoreV1Api | None = None

def get_core_v1_api() -> CoreV1Api:
    """Return a configured CoreV1Api client.

    Legion prefers a local kubeconfig and falls back to in-cluster credentials.
    """
    global _CORE_V1_API
    if _CORE_V1_API is not None:
        return _CORE_V1_API

    _CORE_V1_API = _create_core_v1_api()
    return _CORE_V1_API


def reset_core_v1_api_cache() -> None:
    """Clear the cached CoreV1Api instance for tests or explicit refresh."""
    global _CORE_V1_API
    _CORE_V1_API = None


def _create_core_v1_api() -> CoreV1Api:
    """Construct a configured CoreV1Api client."""
    config_module = import_module("kubernetes.config")
    client_module = import_module("kubernetes.client")
    config_exception_module = import_module("kubernetes.config.config_exception")
    config_exception_type = getattr(config_exception_module, "ConfigException")

    try:
        config_module.load_kube_config()
    except config_exception_type:
        try:
            config_module.load_incluster_config()
        except config_exception_type as exc:
            raise KubernetesConfigError(
                "Unable to load Kubernetes configuration from kubeconfig or in-cluster settings."
            ) from exc
        except Exception as exc:
            raise KubernetesConfigError(
                f"Failed to load in-cluster Kubernetes configuration: {exc}"
            ) from exc
    except Exception as exc:
        raise KubernetesConfigError(f"Failed to load local Kubernetes configuration: {exc}") from exc

    return client_module.CoreV1Api()


def get_api_exception_status(exc: Exception) -> int | None:
    """Return a Kubernetes ApiException status code when available."""
    status = getattr(exc, "status", None)
    return status if isinstance(status, int) else None


def is_connection_error(exc: Exception) -> bool:
    """Heuristically identify connectivity failures from the Kubernetes client stack."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True

    status = get_api_exception_status(exc)
    if status == 0:
        return True

    class_name = type(exc).__name__
    module_name = type(exc).__module__
    if class_name in {"MaxRetryError", "NewConnectionError", "ProtocolError"}:
        return True
    if module_name.startswith("urllib3"):
        return True

    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "connection refused",
            "failed to establish a new connection",
            "max retries exceeded",
            "name or service not known",
            "temporary failure in name resolution",
            "timed out",
        )
    )


def format_api_error(
    action: str,
    *,
    namespace: str | None = None,
    name: str | None = None,
    reason: str | None = None,
) -> str:
    """Format a deterministic operational error string."""
    parts = [action]
    if name:
        parts.append(name)
    if namespace:
        parts.append(f"in namespace {namespace}")
    message = " ".join(parts)
    if reason:
        return f"{message}: {reason}"
    return message


def safe_reason(exc: Exception) -> str:
    """Return a user-facing reason string from a vendor exception."""
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    text = str(exc).strip()
    return text or type(exc).__name__


def resource_to_dict(resource: Any) -> dict[str, Any]:
    """Convert a Kubernetes model object into a plain dict when possible."""
    if hasattr(resource, "to_dict"):
        data = resource.to_dict()
        if isinstance(data, dict):
            return data
    if isinstance(resource, dict):
        return resource
    return {}


def handle_kubernetes_api_error(
    exc: Exception,
    *,
    forbidden_action: str,
    unexpected_action: str,
    namespace: str | None = None,
    name: str | None = None,
    not_found_message: str | None = None,
    missing_message: str | None = None,
) -> str:
    """Return expected API error strings and raise typed errors otherwise."""
    if not_found_message is None:
        not_found_message = missing_message
    status = get_api_exception_status(exc)
    if status == 404 and not_found_message is not None:
        return not_found_message
    if status == 403:
        return format_api_error(forbidden_action, namespace=namespace, name=name, reason=safe_reason(exc))
    if is_connection_error(exc):
        raise KubernetesConnectionError(f"Unable to reach the Kubernetes API: {safe_reason(exc)}") from exc
    raise KubernetesAPIError(
        f"Unexpected Kubernetes API error while {unexpected_action}: {safe_reason(exc)}",
        status_code=status,
    ) from exc
