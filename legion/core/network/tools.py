from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from legion.core.network.ssh_client import SSH
from legion.plumbing.plugins import tool

_MAX_RENDERED_BYTES = 16 * 1024


@dataclass(frozen=True)
class _UsernameOverrideConfig:
    """Proxy SSH config that forces a specific username for lookups."""

    base_config: Any
    username: str

    def lookup(self, host: str) -> dict[str, Any]:
        host_info = dict(self.base_config.lookup(host))
        host_info["user"] = self.username
        return host_info


def _truncate_text(text: str, *, limit: int, label: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text or "<empty>"

    truncated = encoded[:limit].decode("utf-8", errors="ignore")
    omitted = len(encoded) - limit
    return "\n".join(
        [
            truncated,
            f"[{label} truncated: {omitted} bytes omitted]",
        ]
    )


def _format_result_text(text: str) -> str:
    return text or "<empty>"


def _format_command_result(
    *,
    host: str,
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> str:
    stdout_text = _truncate_text(stdout, limit=_MAX_RENDERED_BYTES, label="stdout")
    stderr_text = _truncate_text(stderr, limit=_MAX_RENDERED_BYTES, label="stderr")
    return "\n".join(
        [
            f"SSH command completed on {host}.",
            f"Command: {command}",
            f"Exit Code: {exit_code}",
            "Stdout:",
            _format_result_text(stdout_text),
            "Stderr:",
            _format_result_text(stderr_text),
        ]
    )


def _format_failure_message(host: str, *, connected: bool) -> str:
    if connected:
        return f"SSH command failed on {host}."

    return f"SSH connection failed on {host}."


@tool(
    "ssh_run_command",
    description="Run a command on a remote host via SSH.",
    category="network",
    read_only=False,
)
def ssh_run_command(
    host: str,
    command: str,
    username: str = "root",
    timeout: int = 30,
) -> str:
    """Execute a command over SSH and return a formatted result string."""
    ssh: SSH | None = None
    try:
        with SSH().to(host) as ssh:
            ssh.with_config_resolver(_UsernameOverrideConfig(ssh.config_resolver, username))
            ssh.run(command, timeout=timeout)
            result = ssh.last_result()
    except TimeoutError:
        return f"SSH command timed out on {host}."
    except Exception:
        connected = bool(ssh and ssh.is_connected())
        return _format_failure_message(host, connected=connected)

    if result is None:
        return f"SSH command failed on {host}: no command result was returned."

    return _format_command_result(
        host=result.host,
        command=result.cmd,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
    )
