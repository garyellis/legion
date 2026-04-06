"""Tests for core network inspection tools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from legion.core.network import ssh_run_command
from legion.core.network import tools as network_tools
from legion.core.network.ssh_client import SSH
from legion.plumbing.plugins import ToolMeta, get_tool_meta


class _FakeConfig:
    def __init__(self) -> None:
        self.lookups: list[str] = []

    def lookup(self, host: str) -> dict[str, str]:
        self.lookups.append(host)
        return {"hostname": host, "user": "config-user", "port": "22"}


class _FakeSSH:
    instances: list["_FakeSSH"] = []

    def __init__(self) -> None:
        self.host: str | None = None
        self.closed = False
        self.connected = False
        self.run_calls: list[tuple[str, int]] = []
        self.config_resolver: _FakeConfig | object = _FakeConfig()
        self.result = SimpleNamespace(
            host="example.internal",
            cmd="echo hello",
            stdout="hello",
            stderr="",
            exit_code=0,
        )
        self.raise_on_run: Exception | None = None
        self.last_result_value = self.result
        _FakeSSH.instances.append(self)

    def to(self, host: str) -> "_FakeSSH":
        self.host = host
        return self

    def with_config_resolver(self, config_resolver: object) -> "_FakeSSH":
        self.config_resolver = config_resolver
        return self

    def is_connected(self) -> bool:
        return self.connected

    def __enter__(self) -> "_FakeSSH":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.closed = True

    def run(self, command: str, timeout: int = 600) -> "_FakeSSH":
        self.run_calls.append((command, timeout))
        self.connected = True
        if self.raise_on_run is not None:
            raise self.raise_on_run
        return self

    def last_result(self):
        return self.last_result_value


@pytest.fixture(autouse=True)
def reset_fake_ssh_instances() -> None:
    _FakeSSH.instances = []
    yield
    _FakeSSH.instances = []


class TestToolContract:
    def test_ssh_public_seam_is_additive(self) -> None:
        class _Resolver:
            def lookup(self, host: str) -> dict[str, str]:
                return {"hostname": host, "user": "config-user", "port": "22"}

        ssh = SSH()
        resolver = _Resolver()

        assert ssh.with_config_resolver(resolver) is ssh
        assert ssh.config_resolver is resolver

    def test_package_re_exports_only_ssh_run_command(self) -> None:
        from legion.core import network as network_pkg

        assert network_pkg.ssh_run_command is ssh_run_command
        assert not hasattr(network_pkg, "dns_lookup")
        assert not hasattr(network_pkg, "wake_on_lan")

    def test_tool_metadata(self) -> None:
        assert get_tool_meta(ssh_run_command) == ToolMeta(
            name="ssh_run_command",
            description="Run a command on a remote host via SSH.",
            category="network",
            read_only=False,
            tags=(),
            version="1.0",
        )


class TestSshRunCommand:
    def test_formats_successful_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(network_tools, "SSH", _FakeSSH)

        result = ssh_run_command("example.internal", "echo hello", username="admin", timeout=12)

        assert result == "\n".join(
            [
                "SSH command completed on example.internal.",
                "Command: echo hello",
                "Exit Code: 0",
                "Stdout:",
                "hello",
                "Stderr:",
                "<empty>",
            ]
        )
        assert len(_FakeSSH.instances) == 1
        ssh = _FakeSSH.instances[0]
        assert ssh.host == "example.internal"
        assert ssh.closed is True
        assert ssh.run_calls == [("echo hello", 12)]
        assert isinstance(ssh.config_resolver, network_tools._UsernameOverrideConfig)
        assert ssh.config_resolver.lookup("example.internal")["user"] == "admin"
        assert ssh.config_resolver.base_config.lookups == ["example.internal"]

    def test_returns_descriptive_error_when_run_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failing_ssh = _FakeSSH()
        failing_ssh.raise_on_run = RuntimeError("password=supersecret permission denied")

        monkeypatch.setattr(network_tools, "SSH", lambda: failing_ssh)

        result = ssh_run_command("host-a", "id")

        assert result == "SSH command failed on host-a."
        assert "supersecret" not in result
        assert failing_ssh.closed is True

    def test_returns_timeout_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        timeout_ssh = _FakeSSH()
        timeout_ssh.raise_on_run = TimeoutError("connect timed out")

        monkeypatch.setattr(network_tools, "SSH", lambda: timeout_ssh)

        result = ssh_run_command("host-b", "uptime")

        assert result == "SSH command timed out on host-b."
        assert timeout_ssh.closed is True

    def test_truncates_large_stdout_and_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(network_tools, "_MAX_RENDERED_BYTES", 10)
        large_ssh = _FakeSSH()
        large_ssh.result = SimpleNamespace(
            host="example.internal",
            cmd="echo big",
            stdout="0123456789ABC",
            stderr="XYZ123456789",
            exit_code=0,
        )
        large_ssh.last_result_value = large_ssh.result

        monkeypatch.setattr(network_tools, "SSH", lambda: large_ssh)

        result = ssh_run_command("example.internal", "echo big")

        assert "[stdout truncated: 3 bytes omitted]" in result
        assert "[stderr truncated: 2 bytes omitted]" in result
        assert "0123456789" in result
