"""Register incident command handlers on a Bolt async app."""

from __future__ import annotations

from typing import Any

from legion.services.incident_service import IncidentService
from legion.slack.client import SlackClient
from legion.slack.incident.handlers import (
    handle_incident_command,
    handle_incident_submission,
    handle_resolve_command,
    handle_resolve_submission,
)
from legion.slack.incident.models import SlackIncidentIndex
from legion.slack.registry import registry


def register_incident_handlers(
    app: Any,
    incident_service: IncidentService,
    slack_client: SlackClient,
    slack_index: SlackIncidentIndex,
    *,
    session_link_repo: Any | None = None,
) -> None:
    """Wire /incident and /resolve commands + modal listeners onto *app*."""
    _ = session_link_repo

    # Register metadata so the manifest generator can discover these commands.
    registry.register_metadata(
        "/incident", "Declare a new incident", "[title]"
    )
    registry.register_metadata(
        "/resolve", "Resolve an active incident", ""
    )

    app.command("/incident")(handle_incident_command)

    # Wrap submission handlers with bound dependencies
    async def _on_incident_submit(ack: Any, body: dict, client: Any, view: dict) -> None:
        await handle_incident_submission(
            ack,
            body,
            client,
            view,
            incident_service=incident_service,
            slack_client=slack_client,
            slack_index=slack_index,
            session_link_repo=session_link_repo,
        )

    app.view("create_incident_modal")(_on_incident_submit)

    async def _on_resolve_cmd(ack: Any, body: dict, client: Any) -> None:
        await handle_resolve_command(
            ack,
            body,
            client,
            incident_service=incident_service,
            slack_index=slack_index,
        )

    app.command("/resolve")(_on_resolve_cmd)

    async def _on_resolve_submit(ack: Any, body: dict, client: Any, view: dict) -> None:
        await handle_resolve_submission(
            ack,
            body,
            client,
            view,
            incident_service=incident_service,
            slack_client=slack_client,
            slack_index=slack_index,
        )

    app.view("resolve_incident_modal")(_on_resolve_submit)
