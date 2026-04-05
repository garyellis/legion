"""Slack bot surface — Socket Mode entry point.

Wires infrastructure, domain services, and incident handlers.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from legion.core.slack.client import SlackClient
from legion.core.slack.config import SlackConfig
from legion.plumbing.config.database import DatabaseConfig
from legion.plumbing.database import create_engine
from legion.plumbing.logging import LogFormat, LogOutput, setup_logging
from legion.plumbing.migrations import validate_database_schema_current
from legion.plumbing.scheduler import SchedulerService
from legion.services.incident_service import IncidentService
from legion.services.repository import SQLiteIncidentRepository
from legion.slack.incident.models import SlackIncidentIndex
from legion.slack.incident.persistence import SQLiteSlackIncidentIndex
from legion.slack.incident.wiring import register_incident_handlers
from legion.slack.registry import registry

logger = logging.getLogger(__name__)


def _try_init_chains(agent_cfg):  # type: ignore[no-untyped-def]
    """Optionally initialise AI chains; returns (scribe, post_mortem) or (None, None)."""
    scribe = None
    post_mortem = None
    try:
        from legion.agents.chains.post_mortem import PostMortemChain
        from legion.agents.chains.scribe import ScribeChain

        scribe = ScribeChain(agent_cfg)
        post_mortem = PostMortemChain(agent_cfg)
        logger.info("AI chains initialised (model=%s)", agent_cfg.model_name)
    except Exception as exc:
        logger.warning("AI chains unavailable: %s", exc)
    return scribe, post_mortem


def load_commands(app: AsyncApp) -> None:
    """Dynamically import and register Slack commands from the commands/ directory."""
    commands_dir = os.path.join(os.path.dirname(__file__), "commands")
    for filename in os.listdir(commands_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = f"legion.slack.commands.{filename[:-3]}"
            importlib.import_module(module_name)

    for cmd in registry.list_commands():
        logger.info("Registering Slack command: %s", cmd.name)
        app.command(cmd.name)(cmd.handler)


async def start_socket_mode(slack_config: SlackConfig) -> None:
    """Initialise services and start the Socket Mode handler."""
    # --- Config (fail-fast) -------------------------------------------------
    #### slack_config = SlackConfig()
    if not slack_config.is_available():
        logger.error(
            "Slack config incomplete. Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN."
        )
        return

    # --- Infrastructure -----------------------------------------------------
    app = AsyncApp(token=slack_config.bot_token.get_secret_value())
    slack_client = SlackClient(slack_config)

    db_config = DatabaseConfig()
    engine = create_engine(
        db_config.url, echo=db_config.echo, pool_pre_ping=db_config.pool_pre_ping
    )
    validate_database_schema_current(engine)

    repository = SQLiteIncidentRepository(engine)
    slack_index: SlackIncidentIndex = SQLiteSlackIncidentIndex(engine)
    scheduler = SchedulerService()

    # --- AI chains (optional) -----------------------------------------------
    scribe, post_mortem = None, None
    try:
        from legion.agents.config import AgentConfig

        agent_cfg = AgentConfig()
        if agent_cfg.openai_api_key.get_secret_value():
            scribe, post_mortem = _try_init_chains(agent_cfg)
    except Exception as exc:
        logger.warning("Agent config unavailable: %s", exc)

    # --- Service layer with callbacks ---------------------------------------
    def _on_stale(incident):  # type: ignore[no-untyped-def]
        from legion.slack.views.incident import IncidentView

        state = slack_index.get_by_incident(incident.id)
        if not state:
            return
        ai_draft = None
        if scribe:
            try:
                history = slack_client.fetch_conversation_history(state.channel_id)
                ai_draft = scribe.generate_update(history)
            except Exception as exc:
                logger.error("AI scribe failed: %s", exc)
        msg = IncidentView.render_stale_reminder(incident, ai_draft)
        slack_client.post_message(state.channel_id, msg)

    def _on_resolved(incident, summary):  # type: ignore[no-untyped-def]
        state = slack_index.get_by_incident(incident.id)
        if not state:
            return
        if post_mortem:
            try:
                history = slack_client.fetch_conversation_history(
                    state.channel_id, limit=500
                )
                report = post_mortem.generate_report(history)
                slack_client.post_message(
                    state.channel_id,
                    f":page_facing_up: *Post-Incident Report Generated!*\n\n{report}",
                )
            except Exception as exc:
                logger.error("PIR generation failed: %s", exc)

    incident_service = IncidentService(
        repository,
        on_stale_incident=_on_stale,
        on_incident_resolved=_on_resolved,
    )

    # --- Scheduler ----------------------------------------------------------
    scheduler.add_job(
        incident_service.check_stale_incidents,
        interval_seconds=slack_config.stale_check_interval_seconds,
        id="check_stale_incidents",
    )

    # --- Register handlers --------------------------------------------------
    load_commands(app)
    register_incident_handlers(app, incident_service, slack_client, slack_index)

    @app.event("app_mention")
    async def handle_mentions(event, say):  # type: ignore[no-untyped-def]
        await say(
            f"Hello <@{event['user']}>! Try `/incident` to declare an incident."
        )

    # --- Start --------------------------------------------------------------
    scheduler.start()
    handler = AsyncSocketModeHandler(app, slack_config.app_token.get_secret_value())
    logger.info("Slack app starting in Socket Mode...")
    await handler.start_async()


def main() -> None:
    """Entrypoint for the legion-slack script."""
    slack_config = SlackConfig()
    setup_logging(
        level=slack_config.log_level,
        output=LogOutput.STDOUT,
        fmt=LogFormat[slack_config.log_format],
        quiet_loggers=["slack_sdk", "slack_bolt", "aiohttp"],
    )
    try:
        asyncio.run(start_socket_mode(slack_config))
    except KeyboardInterrupt:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
