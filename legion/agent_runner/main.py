"""Entrypoint for the standalone Legion agent runner."""

from __future__ import annotations

import asyncio
import logging
import signal

from legion.agents.config import AgentConfig
from legion.agent_runner.client import AgentRunnerClient
from legion.agent_runner.config import AgentRunnerConfig
from legion.agent_runner.executor import GraphExecutor
from legion.core.fleet_api.async_client import AsyncFleetAPIClient
from legion.plumbing.logging import LogFormat, LogOutput, setup_logging

logger = logging.getLogger(__name__)


def _install_signal_handlers(client: AgentRunnerClient) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        client.request_shutdown()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, request_shutdown)
        except NotImplementedError:
            signal.signal(signum, lambda *_args: request_shutdown())


async def run_agent_runner(config: AgentRunnerConfig | None = None) -> None:
    """Run the agent runner until shutdown is requested."""

    resolved_config = config or AgentRunnerConfig.from_env()
    agent_config = AgentConfig()

    # Discover tools from entry points (agents/tools.py)
    try:
        from legion.agents.tools import discover_tools
    except ImportError:
        discover_tools = None
        logger.warning("agents optional group not installed; using mock executor")

    tools = discover_tools() if discover_tools is not None else []

    # Build executor
    if tools:
        executor = GraphExecutor(tools=tools, config=agent_config)
    else:
        from legion.agent_runner.executor import DeterministicAgentExecutor

        executor = DeterministicAgentExecutor()
        logger.info("Using deterministic mock executor (no tools discovered)")

    async with AsyncFleetAPIClient(resolved_config.api_url) as registration_client:
        client = AgentRunnerClient(
            config=resolved_config,
            registration_client=registration_client,
            executor=executor,
        )
        _install_signal_handlers(client)
        await client.run()


def main() -> None:
    """Entrypoint for the ``legion-agent`` script."""

    config = AgentRunnerConfig.from_env()
    setup_logging(
        level=config.log_level,
        output=LogOutput.STDOUT,
        fmt=LogFormat[config.log_format.upper()],
        quiet_loggers=["httpcore", "httpx", "uvicorn", "uvicorn.access", "websockets"],
    )
    try:
        asyncio.run(run_agent_runner(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
