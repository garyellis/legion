"""Tests for core Kubernetes inspection tools."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from legion.core.kubernetes import (
    describe_resource,
    get_events,
    list_namespaces,
    pod_logs,
    pod_status,
)
from legion.core.kubernetes import pods as kubernetes_pods
from legion.core.kubernetes import client as kubernetes_client
from legion.core.kubernetes.exceptions import (
    KubernetesAPIError,
    KubernetesConfigError,
    KubernetesConnectionError,
)
from legion.plumbing.plugins import ToolMeta, get_tool_meta


class FakeApiException(Exception):
    """Minimal stand-in for kubernetes.client.ApiException."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class FakeConnectionError(Exception):
    """Minimal stand-in for urllib3 transport errors."""


FakeConnectionError.__module__ = "urllib3.exceptions"


def make_pod(
    name: str,
    *,
    phase: str,
    node_name: str,
    ready: list[bool],
    restart_counts: list[int],
):
    """Build a lightweight pod object for formatter tests."""
    container_statuses = [
        SimpleNamespace(ready=is_ready, restart_count=restart_count)
        for is_ready, restart_count in zip(ready, restart_counts, strict=True)
    ]
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(node_name=node_name),
        status=SimpleNamespace(phase=phase, container_statuses=container_statuses),
    )


def make_event(
    name: str,
    when: datetime,
    *,
    event_type: str,
    reason: str,
    kind: str,
    object_name: str,
    message: str,
):
    """Build a lightweight event object for formatter tests."""
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, creation_timestamp=when),
        event_time=when,
        last_timestamp=when,
        type=event_type,
        reason=reason,
        involved_object=SimpleNamespace(kind=kind, name=object_name),
        message=message,
    )


class FakeResource:
    """Resource object with a Kubernetes-style ``to_dict`` method."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, object]:
        return self._payload


@pytest.fixture(autouse=True)
def reset_kubernetes_client_cache() -> None:
    kubernetes_client.reset_core_v1_api_cache()
    yield
    kubernetes_client.reset_core_v1_api_cache()


class TestToolContract:
    """Metadata and signature contract for B1 Kubernetes tools."""

    @pytest.mark.parametrize(
        ("func", "expected"),
        [
            (
                pod_status,
                ToolMeta(
                    name="pod_status",
                    description="Get pod status in a namespace.",
                    category="kubernetes",
                    read_only=True,
                    tags=(),
                    version="1.0",
                ),
            ),
            (
                pod_logs,
                ToolMeta(
                    name="pod_logs",
                    description="Fetch recent logs from a pod.",
                    category="kubernetes",
                    read_only=True,
                    tags=(),
                    version="1.0",
                ),
            ),
            (
                describe_resource,
                ToolMeta(
                    name="describe_resource",
                    description="Describe a core Kubernetes resource.",
                    category="kubernetes",
                    read_only=True,
                    tags=(),
                    version="1.0",
                ),
            ),
            (
                get_events,
                ToolMeta(
                    name="get_events",
                    description="Get recent events in a namespace.",
                    category="kubernetes",
                    read_only=True,
                    tags=(),
                    version="1.0",
                ),
            ),
            (
                list_namespaces,
                ToolMeta(
                    name="list_namespaces",
                    description="List namespaces in the cluster.",
                    category="kubernetes",
                    read_only=True,
                    tags=(),
                    version="1.0",
                ),
            ),
        ],
    )
    def test_tool_metadata(self, func, expected: ToolMeta) -> None:
        assert get_tool_meta(func) == expected

    def test_function_signatures(self) -> None:
        assert str(inspect.signature(pod_status)) == "(namespace: 'str' = 'default') -> 'str'"
        assert str(inspect.signature(pod_logs)) == "(namespace: 'str', pod_name: 'str', tail_lines: 'int' = 100) -> 'str'"
        assert str(inspect.signature(describe_resource)) == "(kind: 'str', name: 'str', namespace: 'str' = 'default') -> 'str'"
        assert str(inspect.signature(get_events)) == "(namespace: 'str' = 'default', limit: 'int' = 50) -> 'str'"
        assert str(inspect.signature(list_namespaces)) == "() -> 'str'"


class TestClientFactory:
    """Kubernetes client bootstrap behavior."""

    def test_prefers_local_kubeconfig(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        api_instance = object()

        class ConfigException(Exception):
            pass

        def fake_import_module(name: str):
            if name == "kubernetes.config":
                return SimpleNamespace(
                    load_kube_config=lambda: calls.append("kubeconfig"),
                    load_incluster_config=lambda: calls.append("incluster"),
                )
            if name == "kubernetes.client":
                return SimpleNamespace(CoreV1Api=lambda: api_instance)
            if name == "kubernetes.config.config_exception":
                return SimpleNamespace(ConfigException=ConfigException)
            raise AssertionError(name)

        monkeypatch.setattr(kubernetes_client, "import_module", fake_import_module)

        assert kubernetes_client.get_core_v1_api() is api_instance
        assert calls == ["kubeconfig"]

    def test_reuses_cached_client_until_reset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        created: list[object] = []

        class ConfigException(Exception):
            pass

        def build_api() -> object:
            api = object()
            created.append(api)
            return api

        def fake_import_module(name: str):
            if name == "kubernetes.config":
                return SimpleNamespace(
                    load_kube_config=lambda: calls.append("kubeconfig"),
                    load_incluster_config=lambda: calls.append("incluster"),
                )
            if name == "kubernetes.client":
                return SimpleNamespace(CoreV1Api=build_api)
            if name == "kubernetes.config.config_exception":
                return SimpleNamespace(ConfigException=ConfigException)
            raise AssertionError(name)

        monkeypatch.setattr(kubernetes_client, "import_module", fake_import_module)

        first = kubernetes_client.get_core_v1_api()
        second = kubernetes_client.get_core_v1_api()
        kubernetes_client.reset_core_v1_api_cache()
        third = kubernetes_client.get_core_v1_api()

        assert first is second
        assert first is not third
        assert len(created) == 2
        assert calls == ["kubeconfig", "kubeconfig"]

    def test_falls_back_to_incluster_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        api_instance = object()

        class ConfigException(Exception):
            pass

        def load_kube_config() -> None:
            calls.append("kubeconfig")
            raise ConfigException("missing kubeconfig")

        def load_incluster_config() -> None:
            calls.append("incluster")

        def fake_import_module(name: str):
            if name == "kubernetes.config":
                return SimpleNamespace(
                    load_kube_config=load_kube_config,
                    load_incluster_config=load_incluster_config,
                )
            if name == "kubernetes.client":
                return SimpleNamespace(CoreV1Api=lambda: api_instance)
            if name == "kubernetes.config.config_exception":
                return SimpleNamespace(ConfigException=ConfigException)
            raise AssertionError(name)

        monkeypatch.setattr(kubernetes_client, "import_module", fake_import_module)

        assert kubernetes_client.get_core_v1_api() is api_instance
        assert calls == ["kubeconfig", "incluster"]

    def test_raises_kubernetes_config_error_when_no_config_loads(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class ConfigException(Exception):
            pass

        def fail(name: str):
            if name == "kubernetes.config":
                return SimpleNamespace(
                    load_kube_config=lambda: (_ for _ in ()).throw(ConfigException("missing kubeconfig")),
                    load_incluster_config=lambda: (_ for _ in ()).throw(ConfigException("missing service account")),
                )
            if name == "kubernetes.client":
                return SimpleNamespace(CoreV1Api=object)
            if name == "kubernetes.config.config_exception":
                return SimpleNamespace(ConfigException=ConfigException)
            raise AssertionError(name)

        monkeypatch.setattr(kubernetes_client, "import_module", fail)

        with pytest.raises(KubernetesConfigError, match="Unable to load Kubernetes configuration"):
            kubernetes_client.get_core_v1_api()


class TestPodTools:
    """Pod and namespace-scoped tool behavior."""

    def test_pod_status_sorts_and_formats_pods(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            list_namespaced_pod=lambda namespace: SimpleNamespace(
                items=[
                    make_pod("zeta", phase="Pending", node_name="node-b", ready=[False], restart_counts=[0]),
                    make_pod("alpha", phase="Running", node_name="node-a", ready=[True, True], restart_counts=[1, 2]),
                ]
            )
        )
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        result = pod_status("prod")

        assert result == (
            "Pods in namespace prod:\n"
            "- alpha: phase=Running, ready=2/2, restarts=3, node=node-a\n"
            "- zeta: phase=Pending, ready=0/1, restarts=0, node=node-b"
        )

    def test_pod_status_returns_not_found_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(list_namespaced_pod=lambda namespace: (_ for _ in ()).throw(FakeApiException(404, "not found")))
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        assert pod_status("missing") == "Namespace missing not found."

    def test_pod_logs_returns_header_and_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str, int]] = []

        def read_namespaced_pod_log(*, name: str, namespace: str, tail_lines: int) -> str:
            calls.append((namespace, name, tail_lines))
            return "line-one\nline-two\n"

        api = SimpleNamespace(read_namespaced_pod_log=read_namespaced_pod_log)
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        result = pod_logs("prod", "api-0")

        assert calls == [("prod", "api-0", 100)]
        assert result == "Logs for pod api-0 in namespace prod (tail_lines=100):\nline-one\nline-two"

    def test_pod_logs_raises_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            read_namespaced_pod_log=lambda **_kwargs: (_ for _ in ()).throw(FakeConnectionError("connection refused"))
        )
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        with pytest.raises(KubernetesConnectionError, match="Unable to reach the Kubernetes API"):
            pod_logs("prod", "api-0")

    def test_pod_logs_truncates_large_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        oversized_logs = "x" * (kubernetes_pods.MAX_POD_LOG_OUTPUT_CHARS + 25)
        api = SimpleNamespace(
            read_namespaced_pod_log=lambda **_kwargs: oversized_logs
        )
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        result = pod_logs("prod", "api-0")
        prefix = "Logs for pod api-0 in namespace prod (tail_lines=100):\n"
        body = result.removeprefix(prefix)

        assert result.startswith(prefix)
        assert len(body) == kubernetes_pods.MAX_POD_LOG_OUTPUT_CHARS
        assert body.endswith("\n...[truncated]")

    def test_pod_logs_raises_unexpected_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            read_namespaced_pod_log=lambda **_kwargs: (_ for _ in ()).throw(FakeApiException(500, "boom"))
        )
        monkeypatch.setattr("legion.core.kubernetes.pods.get_core_v1_api", lambda: api)

        with pytest.raises(KubernetesAPIError, match="Unexpected Kubernetes API error while reading logs for pod api-0: boom") as exc_info:
            pod_logs("prod", "api-0")

        assert exc_info.value.status_code == 500


class TestResourceTools:
    """Resource description and event formatting behavior."""

    def test_describe_resource_formats_pod_details(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resource = FakeResource(
            {
                "metadata": {
                    "name": "api-0",
                    "namespace": "prod",
                    "labels": {"app": "api"},
                    "annotations": {"owner": "sre"},
                    "creation_timestamp": "2026-04-05T12:00:00+00:00",
                },
                "spec": {"node_name": "node-a"},
                "status": {"phase": "Running", "pod_ip": "10.0.0.1", "host_ip": "192.168.1.10"},
            }
        )
        api = SimpleNamespace(read_namespaced_pod=lambda name, namespace: resource)
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        result = describe_resource("pod", "api-0", "prod")

        assert result == (
            "Kind: Pod\n"
            "Name: api-0\n"
            "Namespace: prod\n"
            "Labels: app=api\n"
            "Annotations: owner=sre\n"
            "Created At: 2026-04-05T12:00:00+00:00\n"
            "Details:\n"
            '{\n'
            '  "host_ip": "192.168.1.10",\n'
            '  "node_name": "node-a",\n'
            '  "phase": "Running",\n'
            '  "pod_ip": "10.0.0.1"\n'
            "}"
        )

    def test_describe_resource_secret_only_exposes_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resource = FakeResource(
            {
                "metadata": {"name": "db-secret", "namespace": "prod"},
                "type": "Opaque",
                "data": {"password": "ZXhhbXBsZQ==", "username": "YWRtaW4="},
            }
        )
        api = SimpleNamespace(read_namespaced_secret=lambda name, namespace: resource)
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        result = describe_resource("secret", "db-secret", "prod")

        assert "password" in result
        assert "username" in result
        assert "ZXhhbXBsZQ==" not in result

    def test_describe_resource_returns_supported_kinds_for_unknown_kind(self) -> None:
        assert (
            describe_resource("deployment", "api")
            == "Unsupported resource kind 'deployment'. Supported kinds: configmap, namespace, node, persistentvolumeclaim, pod, secret, service."
        )

    def test_get_events_sorts_newest_first_and_applies_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        older = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 4, 5, 12, 5, tzinfo=timezone.utc)
        calls: list[tuple[str, int]] = []

        def list_namespaced_event(*, namespace: str, limit: int):
            calls.append((namespace, limit))
            return SimpleNamespace(
                items=[
                    make_event(
                        "event-1",
                        older,
                        event_type="Warning",
                        reason="BackOff",
                        kind="Pod",
                        object_name="api-0",
                        message="Back-off restarting container",
                    ),
                    make_event(
                        "event-2",
                        newer,
                        event_type="Normal",
                        reason="Pulled",
                        kind="Pod",
                        object_name="api-0",
                        message="Container image pulled",
                    ),
                ]
            )

        api = SimpleNamespace(
            list_namespaced_event=list_namespaced_event
        )
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        result = get_events("prod", limit=1)

        assert calls == [("prod", 1)]
        assert result == (
            "Recent events in namespace prod:\n"
            "- 2026-04-05T12:05:00+00:00 Normal Pulled Pod/api-0: Container image pulled"
        )

    def test_get_events_handles_mixed_and_missing_timestamps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        aware = datetime(2026, 4, 5, 12, 5, tzinfo=timezone.utc)
        naive = datetime(2026, 4, 5, 12, 1)
        api = SimpleNamespace(
            list_namespaced_event=lambda *, namespace, limit: SimpleNamespace(
                items=[
                    make_event(
                        "aware",
                        aware,
                        event_type="Normal",
                        reason="Pulled",
                        kind="Pod",
                        object_name="api-0",
                        message="Container image pulled",
                    ),
                    SimpleNamespace(
                        metadata=SimpleNamespace(name="naive", creation_timestamp=naive),
                        event_time=naive,
                        last_timestamp=naive,
                        type="Warning",
                        reason="BackOff",
                        involved_object=SimpleNamespace(kind="Pod", name="api-0"),
                        message="Back-off restarting container",
                    ),
                    SimpleNamespace(
                        metadata=SimpleNamespace(name="missing", creation_timestamp=None),
                        event_time=None,
                        last_timestamp=None,
                        type="Normal",
                        reason="Created",
                        involved_object=SimpleNamespace(kind="Pod", name="api-0"),
                        message="Created container",
                    ),
                ]
            )
        )
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        result = get_events("prod", limit=3)

        assert result == (
            "Recent events in namespace prod:\n"
            "- 2026-04-05T12:05:00+00:00 Normal Pulled Pod/api-0: Container image pulled\n"
            "- 2026-04-05T12:01:00 Warning BackOff Pod/api-0: Back-off restarting container\n"
            "- <unknown> Normal Created Pod/api-0: Created container"
        )

    def test_get_events_returns_forbidden_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            list_namespaced_event=lambda *, namespace, limit: (_ for _ in ()).throw(FakeApiException(403, "RBAC denied"))
        )
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        assert get_events("prod") == "Access denied listing events in namespace prod: RBAC denied"

    def test_get_events_raises_unexpected_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            list_namespaced_event=lambda *, namespace, limit: (_ for _ in ()).throw(FakeApiException(500, "boom"))
        )
        monkeypatch.setattr("legion.core.kubernetes.resources.get_core_v1_api", lambda: api)

        with pytest.raises(KubernetesAPIError, match="Unexpected Kubernetes API error while listing events: boom") as exc_info:
            get_events("prod")

        assert exc_info.value.status_code == 500


class TestClusterTools:
    """Cluster-scoped Kubernetes tool behavior."""

    def test_list_namespaces_sorts_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(
            list_namespace=lambda: SimpleNamespace(
                items=[
                    SimpleNamespace(metadata=SimpleNamespace(name="zeta"), status=SimpleNamespace(phase="Active")),
                    SimpleNamespace(metadata=SimpleNamespace(name="alpha"), status=SimpleNamespace(phase="Active")),
                ]
            )
        )
        monkeypatch.setattr("legion.core.kubernetes.cluster.get_core_v1_api", lambda: api)

        assert list_namespaces() == "Namespaces in the cluster:\n- alpha: phase=Active\n- zeta: phase=Active"

    def test_list_namespaces_raises_connection_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(list_namespace=lambda: (_ for _ in ()).throw(FakeConnectionError("timed out")))
        monkeypatch.setattr("legion.core.kubernetes.cluster.get_core_v1_api", lambda: api)

        with pytest.raises(KubernetesConnectionError, match="Unable to reach the Kubernetes API"):
            list_namespaces()

    def test_list_namespaces_raises_unexpected_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api = SimpleNamespace(list_namespace=lambda: (_ for _ in ()).throw(FakeApiException(500, "boom")))
        monkeypatch.setattr("legion.core.kubernetes.cluster.get_core_v1_api", lambda: api)

        with pytest.raises(KubernetesAPIError, match="Unexpected Kubernetes API error while listing namespaces: boom") as exc_info:
            list_namespaces()

        assert exc_info.value.status_code == 500
