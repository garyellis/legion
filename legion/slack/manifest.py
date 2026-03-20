"""Slack app manifest generator.

Produces a complete App Manifest JSON from the command registry and
declared OAuth scopes / event subscriptions. Run via::

    legion-cli slack manifest
    # or
    python -m legion.slack.manifest
"""

from __future__ import annotations

import importlib
import json
import os
from typing import Any

from legion.slack.registry import registry

# ── OAuth scopes required by this app ──────────────────────────────────────

BOT_TOKEN_SCOPES: list[str] = [
    "app_mentions:read",
    # Messaging
    "chat:write",
    "chat:write.public",
    # Slash commands
    "commands",
    # Channel management (incident channels)
    "channels:manage",
    "channels:join",
    "groups:write",
    "mpim:write",
    "im:write",
    # Pins (dashboard message)
    "pins:write",
    # Read history (AI summaries)
    "channels:history",
    "groups:history",
    # User info
    "users:read",
    # Channel membership
    "channels:read",
    "groups:read",

    "conversations.connect:manage",
    "conversations.connect:read",
    "conversations.connect:write"
]

# ── Event subscriptions ────────────────────────────────────────────────────

BOT_EVENTS: list[str] = [
    "app_mention",
    "message.channels",
]

# ── App metadata ───────────────────────────────────────────────────────────

APP_NAME = "legion-bot"
APP_DESCRIPTION = "Legion platform Slack surface — lab ops, network tools, incident management"


def _load_all_commands() -> None:
    """Import all command modules so they register with the global registry."""
    commands_dir = os.path.join(os.path.dirname(__file__), "commands")
    if os.path.isdir(commands_dir):
        for filename in os.listdir(commands_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                importlib.import_module(f"legion.slack.commands.{filename[:-3]}")

    # Incident commands register metadata when wiring is imported.
    # We import the module so register_metadata calls execute, but we don't
    # need to call register_incident_handlers (that needs runtime DI).
    # Instead, register the metadata directly here for manifest purposes.
    registry.register_metadata("/incident", "Declare a new incident", "[title]")
    registry.register_metadata("/resolve", "Resolve an active incident", "")


def build_manifest() -> dict[str, Any]:
    """Build a Slack App Manifest dict.

    See https://api.slack.com/reference/manifests
    """
    _load_all_commands()

    slash_commands: dict[str, dict[str, str]] = {}
    for cmd in registry.list_all_metadata():
        slash_commands[cmd.name] = {
            "description": cmd.description,
        }
        if cmd.usage_hint:
            slash_commands[cmd.name]["usage_hint"] = cmd.usage_hint

    return {
        "_metadata": {"major_version": 2, "minor_version": 0},
        "display_information": {
            "name": APP_NAME,
            "description": APP_DESCRIPTION,
        },
        "features": {
            "bot_user": {
                "display_name": APP_NAME,
                "always_online": True,
            },
            "slash_commands": [
                {"command": name, **meta}
                for name, meta in sorted(slash_commands.items())
            ],
        },
        "oauth_config": {
            "scopes": {
                "bot": sorted(BOT_TOKEN_SCOPES),
            },
        },
        "settings": {
            "event_subscriptions": {
                "bot_events": sorted(BOT_EVENTS),
            },
            "interactivity": {
                "is_enabled": True,
            },
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }


def main() -> None:
    print(json.dumps(build_manifest(), indent=2))


if __name__ == "__main__":
    main()
