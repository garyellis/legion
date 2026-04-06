"""Static packaging contract tests for Kubernetes tool plugins."""

from __future__ import annotations

import importlib
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

    expected_entry_points = {
        "pod_status": "legion.core.kubernetes.pods:pod_status",
        "pod_logs": "legion.core.kubernetes.pods:pod_logs",
        "describe_resource": "legion.core.kubernetes.resources:describe_resource",
        "get_events": "legion.core.kubernetes.resources:get_events",
        "list_namespaces": "legion.core.kubernetes.cluster:list_namespaces",
        "db_query": "legion.core.database.tools:db_query",
        "db_tables": "legion.core.database.tools:db_tables",
        "db_table_schema": "legion.core.database.tools:db_table_schema",
        "db_connection_check": "legion.core.database.tools:db_connection_check",
        "ssh_run_command": "legion.core.network.tools:ssh_run_command",
    }

    assert set(expected_entry_points).issubset(entry_points)
    assert len(entry_points) == len(set(entry_points))

    for name, target in expected_entry_points.items():
        assert entry_points[name] == target
        module_name, attr_name = target.split(":")
        module = importlib.import_module(module_name)
        assert getattr(module, attr_name) is not None
