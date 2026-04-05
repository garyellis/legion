"""Service-layer coordination for dispatching jobs to connected agents."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from legion.domain.agent import Agent
from legion.domain.job import Job
from legion.domain.prompt_config import PromptConfig
from legion.services.dispatch_service import DispatchService
from legion.services.fleet_repository import FleetRepository

logger = logging.getLogger(__name__)

OnJobDelivery = Callable[[Job, Agent, PromptConfig | None], Awaitable[None]]


class AgentDeliveryService:
    """Dispatch pending work for an agent group and deliver it via a callback."""

    def __init__(self, dispatch_service: DispatchService, fleet_repo: FleetRepository) -> None:
        self._dispatch_service = dispatch_service
        self._fleet_repo = fleet_repo

    async def dispatch_pending_for_group(
        self,
        agent_group_id: str,
        deliver_job: OnJobDelivery,
    ) -> list[tuple[Job, Agent]]:
        loop = asyncio.get_running_loop()
        prompt_config = await loop.run_in_executor(
            None, self._fleet_repo.get_prompt_config_by_agent_group, agent_group_id,
        )
        delivered: list[tuple[Job, Agent]] = []

        while True:
            dispatched = await loop.run_in_executor(
                None, self._dispatch_service.dispatch_pending, agent_group_id,
            )
            if not dispatched:
                return delivered

            delivery_failed = False
            for job, agent in dispatched:
                try:
                    await deliver_job(job, agent, prompt_config)
                except Exception:
                    delivery_failed = True
                    logger.exception(
                        "Failed to deliver job %s to agent %s",
                        job.id,
                        agent.id,
                    )
                    await loop.run_in_executor(
                        None, self._dispatch_service.disconnect_agent, agent.id,
                    )
                else:
                    delivered.append((job, agent))

            if not delivery_failed:
                return delivered
