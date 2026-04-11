"""Agent session handler - extracts protocol/business logic from the WebSocket transport layer.

Processes parsed agent-to-server messages and returns result objects describing
the effects the caller (transport layer) should perform. This keeps the handler
fully synchronous and testable without any WebSocket or asyncio dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, assert_never

from legion.domain.audit_event import AuditAction, AuditEvent
from legion.domain.job import Job
from legion.domain.message import AuthorType, Message, MessageType
from legion.domain.protocol import (
    AgentToServerMessage,
    AuditEventMessage,
    HeartbeatMessage,
    JobFailedMessage,
    JobProgressMessage,
    JobResultMessage,
    JobStartedMessage,
    MessageEmitMessage,
)
from legion.services.audit_service import AuditService
from legion.services.dispatch_service import DispatchService
from legion.services.exceptions import DispatchError
from legion.services.job_repository import JobRepository
from legion.services.message_service import MessageService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result objects — describe effects the transport layer should perform
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedispatchPendingForGroup:
    """Request that the caller redispatch pending work for an agent group."""

    agent_group_id: str


type HandleEffect = RedispatchPendingForGroup


@dataclass(frozen=True)
class HandleResult:
    """Outcome of processing a single agent-to-server message.

    Attributes:
        effects: Typed follow-up actions the transport layer should perform.
        ignored: True when the message was silently dropped (e.g. ownership
            violation, unknown job, DispatchError).
    """

    effects: tuple[HandleEffect, ...] = ()
    ignored: bool = False

    def __post_init__(self) -> None:
        if self.ignored and self.effects:
            raise ValueError("ignored HandleResult cannot include effects")


_IGNORED = HandleResult(ignored=True)
_OK = HandleResult()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class AgentSessionHandler:
    """Processes parsed agent-to-server messages, applying business logic.

    All dependencies are constructor-injected.  ``message_service`` and
    ``audit_service`` are optional — when ``None`` the corresponding message
    types are silently skipped with a debug log.
    """

    def __init__(
        self,
        dispatch_service: DispatchService,
        job_repo: JobRepository,
        *,
        message_service: MessageService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._dispatch_service = dispatch_service
        self._job_repo = job_repo
        self._message_service = message_service
        self._audit_service = audit_service

    # -- public entry point -------------------------------------------------

    def handle(
        self,
        message: AgentToServerMessage,
        agent_id: str,
        agent_group_id: str,
    ) -> HandleResult:
        """Dispatch *message* to the appropriate handler method.

        Returns a :class:`HandleResult` telling the caller what side-effects
        to perform (e.g. dispatching pending work for a group).
        """
        if isinstance(message, HeartbeatMessage):
            return self._handle_heartbeat(agent_id)

        if isinstance(message, JobStartedMessage):
            return self._handle_job_started(message, agent_id)

        if isinstance(message, JobResultMessage):
            return self._handle_job_result(message, agent_id, agent_group_id)

        if isinstance(message, JobFailedMessage):
            return self._handle_job_failed(message, agent_id, agent_group_id)

        if isinstance(message, JobProgressMessage):
            return self._handle_job_progress(message, agent_id)

        if isinstance(message, MessageEmitMessage):
            return self._handle_message_emit(message, agent_id)

        if isinstance(message, AuditEventMessage):
            return self._handle_audit_event(message, agent_id)

        assert_never(message)

    # -- individual handlers ------------------------------------------------

    def _handle_heartbeat(self, agent_id: str) -> HandleResult:
        self._dispatch_service.heartbeat(agent_id)
        return _OK

    def _handle_job_started(
        self,
        message: JobStartedMessage,
        agent_id: str,
    ) -> HandleResult:
        job = self._verify_job_ownership(
            self._job_repo.get_by_id(message.job_id),
            agent_id,
            "job_started",
        )
        if job is None:
            return _IGNORED
        job.start()
        self._job_repo.save(job)
        return _OK

    def _handle_job_result(
        self,
        message: JobResultMessage,
        agent_id: str,
        agent_group_id: str,
    ) -> HandleResult:
        try:
            self._dispatch_service.complete_job(
                message.job_id, message.result, agent_id=agent_id,
            )
        except DispatchError:
            logger.warning(
                "Ignoring job_result for unknown job %s from agent %s",
                message.job_id,
                agent_id,
            )
            return _IGNORED
        return HandleResult(
            effects=(RedispatchPendingForGroup(agent_group_id),),
        )

    def _handle_job_failed(
        self,
        message: JobFailedMessage,
        agent_id: str,
        agent_group_id: str,
    ) -> HandleResult:
        try:
            self._dispatch_service.fail_job(
                message.job_id, message.error, agent_id=agent_id,
            )
        except DispatchError:
            logger.warning(
                "Ignoring job_failed for unknown job %s from agent %s",
                message.job_id,
                agent_id,
            )
            return _IGNORED
        return HandleResult(
            effects=(RedispatchPendingForGroup(agent_group_id),),
        )

    def _handle_job_progress(
        self,
        message: JobProgressMessage,
        agent_id: str,
    ) -> HandleResult:
        job = self._verify_job_ownership(
            self._job_repo.get_by_id(message.job_id),
            agent_id,
            "job_progress",
        )
        if job is None:
            return _IGNORED
        logger.info(
            "job_progress job=%s step=%s detail=%s seq=%d",
            message.job_id, message.step, message.detail, message.sequence,
        )
        return _OK

    def _handle_message_emit(
        self,
        message: MessageEmitMessage,
        agent_id: str,
    ) -> HandleResult:
        job = self._verify_job_ownership(
            self._job_repo.get_by_id(message.job_id),
            agent_id,
            "message_emit",
        )
        if job is None:
            return _IGNORED

        if self._message_service is None:
            logger.debug(
                "message_service not available, skipping message_emit for job %s",
                message.job_id,
            )
            return _OK

        try:
            domain_message = Message(
                org_id=job.org_id,
                session_id=job.session_id,
                author_id=job.agent_id or agent_id,
                author_type=AuthorType.AGENT,
                message_type=MessageType(message.message_type),
                content=message.content,
                job_id=message.job_id,
                metadata=message.metadata,
            )
            self._message_service.emit(domain_message)
        except Exception:
            logger.warning(
                "Failed to persist message_emit for job %s from agent %s",
                message.job_id, agent_id, exc_info=True,
            )
        return _OK

    def _handle_audit_event(
        self,
        message: AuditEventMessage,
        agent_id: str,
    ) -> HandleResult:
        job = self._verify_job_ownership(
            self._job_repo.get_by_id(message.job_id),
            agent_id,
            "audit_event",
        )
        if job is None:
            return _IGNORED

        if self._audit_service is None:
            logger.debug(
                "audit_service not available, skipping audit_event for job %s",
                message.job_id,
            )
            return _OK

        try:
            try:
                audit_action = AuditAction(message.action)
            except ValueError:
                logger.warning("Unknown audit action %r, defaulting to TOOL_CALL", message.action)
                audit_action = AuditAction.TOOL_CALL

            output_dict: dict[str, Any] | None = None
            if message.tool_output is not None or message.error is not None:
                output_dict = {}
                if message.tool_output is not None:
                    output_dict["raw"] = message.tool_output
                if message.error is not None:
                    output_dict["error"] = message.error

            audit_event = AuditEvent(
                job_id=message.job_id,
                agent_id=job.agent_id or agent_id,
                session_id=job.session_id,
                org_id=job.org_id,
                action=audit_action,
                tool_name=message.tool_name,
                input={"raw": message.tool_input},
                output=output_dict,
                duration_ms=message.duration_ms,
            )
            self._audit_service.emit(audit_event)
        except Exception:
            logger.warning(
                "Failed to persist audit_event for job %s from agent %s",
                message.job_id, agent_id, exc_info=True,
            )
        return _OK

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _verify_job_ownership(
        job: Job | None,
        agent_id: str,
        message_type: str,
    ) -> Job | None:
        """Return the job if it exists and belongs to the agent, else None."""
        if job is None:
            return None
        if job.agent_id != agent_id:
            logger.warning(
                "ownership_violation agent=%s sent %s for job %s owned by %s",
                agent_id, message_type, job.id, job.agent_id,
            )
            return None
        return job
