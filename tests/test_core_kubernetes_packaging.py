"""Static packaging contract tests for Kubernetes tool plugins."""

from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
def test_pyproject_declares_kubernetes_runtime_dependency() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)

    dependencies = data["project"]["dependencies"]
    assert "kubernetes>=29.0,<32" in dependencies


def test_pyproject_declares_legion_tool_entry_points() -> None:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as fh:
        data = tomllib.load(fh)

    entry_points = data["project"]["entry-points"]["legion.tools"]
    assert entry_points == {
        "pod_status": "legion.core.kubernetes.pods:pod_status",
        "pod_logs": "legion.core.kubernetes.pods:pod_logs",
        "describe_resource": "legion.core.kubernetes.resources:describe_resource",
        "get_events": "legion.core.kubernetes.resources:get_events",
        "list_namespaces": "legion.core.kubernetes.cluster:list_namespaces",
    }
