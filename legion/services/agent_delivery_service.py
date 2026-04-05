"""Service-layer coordination for dispatching jobs to connected agents."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging

from legion.domain.agent import Agent
from legion.domain.job import Job
from legion.services.dispatch_service import DispatchService

logger = logging.getLogger(__name__)

OnJobDelivery = Callable[[Job, Agent], Awaitable[None]]


class AgentDeliveryService:
    """Dispatch pending work for an agent group and deliver it via a callback."""

    def __init__(self, dispatch_service: DispatchService) -> None:
        self._dispatch_service = dispatch_service

    async def dispatch_pending_for_group(
        self,
        agent_group_id: str,
        deliver_job: OnJobDelivery,
    ) -> list[tuple[Job, Agent]]:
        delivered: list[tuple[Job, Agent]] = []

        while True:
            dispatched = self._dispatch_service.dispatch_pending(agent_group_id)
            if not dispatched:
                return delivered

            delivery_failed = False
            for job, agent in dispatched:
                try:
                    await deliver_job(job, agent)
                except Exception:
                    delivery_failed = True
                    logger.exception(
                        "Failed to deliver job %s to agent %s",
                        job.id,
                        agent.id,
                    )
                    self._dispatch_service.disconnect_agent(agent.id)
                else:
                    delivered.append((job, agent))

            if not delivery_failed:
                return delivered
