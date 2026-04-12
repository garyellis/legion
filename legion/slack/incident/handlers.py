"""Async Slack handlers for /incident and /resolve commands."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from legion.domain.incident import IncidentSeverity
from legion.services.incident_service import IncidentService
from legion.services.fleet_repository import SQLiteFleetRepository
from legion.slack.client import SlackClient
from legion.slack.incident.models import SlackIncidentIndex, SlackIncidentState
from legion.slack.views.incident import IncidentView
from legion.services.session_repository import SQLiteSessionRepository
from legion.services.session_service import SessionService

logger = logging.getLogger(__name__)


async def handle_incident_command(ack: Any, body: dict, client: Any) -> None:
    """Open the 'Declare Incident' modal."""
    await ack()
    view = IncidentView.render_incident_modal()
    view["private_metadata"] = json.dumps(
        {"origin_channel_id": body["channel_id"]}
    )
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=view,
    )


def _get_engine_from_repo(repo: Any) -> Any | None:
    """Extract the SQLAlchemy engine from a repository if it is available."""
    engine = getattr(repo, "_engine", None)
    if engine is not None:
        return engine

    session_factory = getattr(repo, "_session_factory", None)
    if session_factory is None:
        return None

    factory_kwargs = getattr(session_factory, "kw", None)
    if not isinstance(factory_kwargs, dict):
        return None
    return factory_kwargs.get("bind")


def _get_origin_channel_id(view: dict[str, Any]) -> str | None:
    """Read the originating Slack channel from modal private metadata."""
    private_metadata = view.get("private_metadata")
    if not private_metadata:
        return None

    try:
        metadata = json.loads(private_metadata)
    except json.JSONDecodeError:
        logger.warning("Incident modal private metadata was invalid JSON")
        return None

    origin_channel_id = metadata.get("origin_channel_id")
    if not isinstance(origin_channel_id, str) or not origin_channel_id:
        logger.warning("Incident modal metadata missing origin_channel_id")
        return None
    return origin_channel_id


def _bind_incident_session(
    *,
    incident_id: str,
    incident_channel_id: str,
    dashboard_ts: str,
    view: dict[str, Any],
    incident_service: IncidentService,
    slack_link_repo: Any | None,
) -> None:
    """Best-effort session binding for incident channels."""
    origin_channel_id = _get_origin_channel_id(view)
    if origin_channel_id is None:
        logger.info(
            "Skipping session binding for incident %s: missing origin channel",
            incident_id,
        )
        return

    if slack_link_repo is None:
        logger.warning(
            "Skipping session binding for incident %s: missing Slack session-link repo",
            incident_id,
        )
        return

    engine = _get_engine_from_repo(slack_link_repo) or _get_engine_from_repo(
        incident_service.repository
    )
    if engine is None:
        logger.warning(
            "Skipping session binding for incident %s: no shared DB engine available",
            incident_id,
        )
        return

    fleet_repo = SQLiteFleetRepository(engine)
    session_repo = SQLiteSessionRepository(engine)
    session_service = SessionService(session_repo, fleet_repo, slack_link_repo)

    mapping = fleet_repo.get_channel_mapping_by_channel(origin_channel_id)
    if mapping is None:
        logger.info(
            "Skipping session binding for incident %s: no mapping for origin channel %s",
            incident_id,
            origin_channel_id,
        )
        return

    session, created = session_service.get_or_create(
        mapping.org_id,
        mapping.agent_group_id,
        incident_channel_id,
        dashboard_ts,
    )
    logger.info(
        "Incident %s bound to session %s (%s) via origin channel %s%s",
        incident_id,
        session.id,
        "created" if created else "reused",
        origin_channel_id,
    )


async def handle_incident_submission(
    ack: Any,
    body: dict,
    client: Any,
    view: dict,
    *,
    incident_service: IncidentService,
    slack_client: SlackClient,
    slack_index: SlackIncidentIndex,
    session_link_repo: Any | None = None,
) -> None:
    """Process the 'Declare Incident' modal submission."""
    await ack()

    user_id = body["user"]["id"]
    values = view["state"]["values"]
    title = values["title_block"]["title_input"]["value"]
    description = values["desc_block"]["desc_input"]["value"]
    severity_str = values["severity_block"]["severity_input"]["selected_option"]["value"]
    interval = int(
        values["interval_block"]["interval_input"]["selected_option"]["value"]
    )

    try:
        incident = incident_service.create_incident(
            title=title,
            description=description,
            severity=IncidentSeverity(severity_str),
            commander_id=user_id,
            check_in_interval=interval,
        )

        # Create dedicated channel
        safe_title = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:40]
        channel_name = f"inc-{safe_title}-{incident.id[:8]}"
        channel_id = slack_client.create_channel(channel_name)

        slack_client.invite_users(channel_id, [user_id])
        slack_client.set_channel_topic(
            channel_id,
            f"INCIDENT: {title} | Sev: {severity_str} | Commander: <@{user_id}> | Status: {incident.status.value}",
        )

        # Post & pin welcome dashboard
        blocks = IncidentView.render_welcome_dashboard(incident, user_id)
        dashboard_ts = slack_client.post_message(
            channel_id, f"Incident Declared: {title}", blocks=blocks
        )
        slack_client.pin_message(channel_id, dashboard_ts)

        # Track Slack state
        state = SlackIncidentState(incident.id, channel_id, dashboard_ts)
        slack_index.register(state)

        _bind_incident_session(
            incident_id=incident.id,
            incident_channel_id=channel_id,
            dashboard_ts=dashboard_ts,
            view=view,
            incident_service=incident_service,
            slack_link_repo=session_link_repo,
        )

        await client.chat_postMessage(
            channel=user_id,
            text=f"Incident created! Go to <#{channel_id}>",
        )

    except Exception:
        logger.exception("Failed to create incident")
        await client.chat_postMessage(
            channel=user_id,
            text=":warning: Failed to create incident.",
        )


async def handle_resolve_command(
    ack: Any,
    body: dict,
    client: Any,
    *,
    incident_service: IncidentService,
    slack_index: SlackIncidentIndex,
) -> None:
    """Open the 'Resolve Incident' modal."""
    await ack()

    channel_id = body["channel_id"]
    state = slack_index.get_by_channel(channel_id)
    if not state:
        await client.chat_postMessage(
            channel=channel_id,
            text=":warning: This command is only available in active incident channels.",
        )
        return

    incident = incident_service.get_incident(state.incident_id)
    if not incident:
        return

    stop_time = datetime.now(timezone.utc).isoformat()
    metadata = json.dumps(
        {
            "incident_id": incident.id,
            "stop_time": stop_time,
            "channel_id": channel_id,
        }
    )

    await client.views_open(
        trigger_id=body["trigger_id"],
        view=IncidentView.render_resolve_modal(incident, metadata),
    )


async def handle_resolve_submission(
    ack: Any,
    body: dict,
    client: Any,
    view: dict,
    *,
    incident_service: IncidentService,
    slack_client: SlackClient,
    slack_index: SlackIncidentIndex,
) -> None:
    """Process the 'Resolve Incident' modal submission."""
    await ack()

    user_id = body["user"]["id"]
    summary = view["state"]["values"]["summary_block"]["summary_input"]["value"]

    try:
        metadata = json.loads(view["private_metadata"])
        incident_id = metadata["incident_id"]
        stop_time = datetime.fromisoformat(metadata["stop_time"])
        channel_id = metadata["channel_id"]

        incident = incident_service.resolve_incident(
            incident_id=incident_id,
            user_id=user_id,
            summary=summary,
            resolved_at=stop_time,
        )
    except Exception:
        logger.exception("Failed to resolve incident")
        await client.chat_postMessage(
            channel=user_id,
            text=":warning: Failed to resolve incident.",
        )
        return

    # Update channel topic + pinned dashboard + post resolution — best effort
    try:
        slack_client.set_channel_topic(
            channel_id,
            f"INCIDENT: {incident.title} | Sev: {incident.severity.value} | Commander: <@{user_id}> | Status: {incident.status.value}",
        )

        state = slack_index.get_by_incident(incident.id)
        if state and state.dashboard_message_ts:
            dashboard_blocks = IncidentView.render_welcome_dashboard(incident, user_id)
            slack_client.update_message(
                channel_id,
                state.dashboard_message_ts,
                f"Incident Declared: {incident.title}",
                blocks=dashboard_blocks,
            )

        blocks = IncidentView.render_resolution(incident, user_id, summary)
        slack_client.post_message(channel_id, "Incident Resolved", blocks=blocks)
    except Exception:
        logger.exception("Failed to update channel after resolve (incident was resolved successfully)")
