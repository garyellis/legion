"""Async Slack handlers for /incident and /resolve commands."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from legion.core.slack.client import SlackClient
from legion.domain.incident import IncidentSeverity
from legion.services.incident_service import IncidentService
from legion.slack.incident.models import SlackIncidentIndex, SlackIncidentState
from legion.slack.views.incident import IncidentView

logger = logging.getLogger(__name__)


async def handle_incident_command(ack: Any, body: dict, client: Any) -> None:
    """Open the 'Declare Incident' modal."""
    await ack()
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=IncidentView.render_incident_modal(),
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
