"""Agent backend registry for external AI CLI tools.

Each backend describes how to invoke an AI agent CLI with a prompt.
Adding a new agent = one entry in AGENT_BACKENDS.
"""

from __future__ import annotations

from dataclasses import dataclass

from legion.plumbing.subprocess import find_on_path, run_capture_text, run_passthrough


@dataclass(frozen=True, slots=True)
class AgentBackend:
    """Describes how to invoke an AI agent CLI."""

    binary: str
    args: tuple[str, ...]  # prompt is appended as the last argument


AGENT_BACKENDS: dict[str, AgentBackend] = {
    "claude": AgentBackend(binary="claude", args=("claude", "-p")),
    "codex": AgentBackend(binary="codex", args=("codex", "exec")),
}


def available_agents() -> list[str]:
    """Return sorted list of registered agent names."""
    return sorted(AGENT_BACKENDS)


def run_agent_prompt(agent: str, prompt: str) -> int:
    """Run an AI agent CLI with a prompt. Returns the process exit code.

    Raises ValueError if agent is unknown.
    Raises FileNotFoundError if the agent binary is not on PATH.
    """
    backend = AGENT_BACKENDS.get(agent)
    if backend is None:
        available = ", ".join(available_agents())
        msg = f"Unknown agent: {agent}. Available: {available}"
        raise ValueError(msg)

    if not find_on_path(backend.binary):
        msg = f"{backend.binary} CLI not found on PATH"
        raise FileNotFoundError(msg)

    return run_passthrough([*backend.args, prompt])


def run_agent_capture(agent: str, prompt: str) -> tuple[int, str]:
    """Run an AI agent CLI and capture its output. Returns (exit_code, stdout).

    Raises ValueError if agent is unknown.
    Raises FileNotFoundError if the agent binary is not on PATH.
    """
    backend = AGENT_BACKENDS.get(agent)
    if backend is None:
        available = ", ".join(available_agents())
        msg = f"Unknown agent: {agent}. Available: {available}"
        raise ValueError(msg)

    if not find_on_path(backend.binary):
        msg = f"{backend.binary} CLI not found on PATH"
        raise FileNotFoundError(msg)

    result = run_capture_text([*backend.args, prompt])
    return result.returncode, result.stdout
