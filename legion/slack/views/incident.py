"""Incident Block Kit views — extends SlackView."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from legion.domain.incident import Incident
from legion.slack.views.base import SlackView


class IncidentView(SlackView):
    """Renders incident-related Block Kit payloads."""

    @staticmethod
    def render_incident_modal() -> dict[str, Any]:
        return {
            "type": "modal",
            "callback_id": "create_incident_modal",
            "title": {"type": "plain_text", "text": "Declare Incident"},
            "submit": {"type": "plain_text", "text": "Mobilize"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "title_block",
                    "element": {"type": "plain_text_input", "action_id": "title_input"},
                    "label": {"type": "plain_text", "text": "Title"},
                },
                {
                    "type": "input",
                    "block_id": "desc_block",
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "desc_input",
                    },
                    "label": {"type": "plain_text", "text": "Description"},
                },
                {
                    "type": "input",
                    "block_id": "severity_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "Select severity"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "SEV1 (Critical)"}, "value": "SEV1"},
                            {"text": {"type": "plain_text", "text": "SEV2 (Major)"}, "value": "SEV2"},
                            {"text": {"type": "plain_text", "text": "SEV3 (Minor)"}, "value": "SEV3"},
                            {"text": {"type": "plain_text", "text": "SEV4 (Trivial)"}, "value": "SEV4"},
                        ],
                        "action_id": "severity_input",
                    },
                    "label": {"type": "plain_text", "text": "Severity"},
                },
                {
                    "type": "input",
                    "block_id": "interval_block",
                    "element": {
                        "type": "static_select",
                        "placeholder": {"type": "plain_text", "text": "Select check-in interval"},
                        "initial_option": {"text": {"type": "plain_text", "text": "Every 30 mins"}, "value": "30"},
                        "options": [
                            {"text": {"type": "plain_text", "text": "Every 2 mins (testing)"}, "value": "2"},
                            {"text": {"type": "plain_text", "text": "Every 15 mins"}, "value": "15"},
                            {"text": {"type": "plain_text", "text": "Every 30 mins"}, "value": "30"},
                            {"text": {"type": "plain_text", "text": "Every 60 mins"}, "value": "60"},
                        ],
                        "action_id": "interval_input",
                    },
                    "label": {"type": "plain_text", "text": "Status Update Schedule"},
                },
            ],
        }

    @staticmethod
    def render_resolve_modal(incident: Incident, private_metadata: str) -> dict[str, Any]:
        return {
            "type": "modal",
            "callback_id": "resolve_incident_modal",
            "private_metadata": private_metadata,
            "title": {"type": "plain_text", "text": "Resolve Incident"},
            "submit": {"type": "plain_text", "text": "Resolve"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                SlackView.section(f"Resolving incident: *{incident.title}*"),
                {
                    "type": "input",
                    "block_id": "summary_block",
                    "element": {
                        "type": "plain_text_input",
                        "multiline": True,
                        "action_id": "summary_input",
                    },
                    "label": {"type": "plain_text", "text": "Resolution Summary (What fixed it?)"},
                },
            ],
        }

    @staticmethod
    def render_welcome_dashboard(incident: Incident, user_id: str) -> list[dict[str, Any]]:
        return [
            SlackView.header(f"Incident Declared: {incident.title}"),
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n{incident.severity.value}"},
                    {"type": "mrkdwn", "text": f"*Commander:*\n<@{user_id}>"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{incident.status.value}"},
                ],
            },
            SlackView.section(f"*Description:*\n{incident.description}"),
            SlackView.divider(),
            SlackView.section(
                f"*Next Steps:* A status update is due in {incident.check_in_interval} minutes. The bot will remind you."
            ),
        ]

    @staticmethod
    def render_resolution(incident: Incident, user_id: str, summary: str) -> list[dict[str, Any]]:
        duration_str = str(timedelta(seconds=incident.duration_seconds or 0))
        return [
            SlackView.header("Incident Resolved"),
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Duration:*\n{duration_str}"},
                    {"type": "mrkdwn", "text": f"*Resolver:*\n<@{user_id}>"},
                ],
            },
            SlackView.section(f"*Resolution Summary:*\n{summary}"),
        ]

    @staticmethod
    def render_stale_reminder(incident: Incident, ai_draft: str | None = None) -> str:
        msg = (
            f":alarm_clock: *Status Check:* It has been {incident.check_in_interval}m "
            #f"since the last update. <@{incident.commander_id}> please provide a status update."
        )
        if ai_draft:
            msg += f"\n\n:robot_face: *Situation Report:*\n{ai_draft}"
        return msg
