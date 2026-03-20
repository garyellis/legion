from typing import Any, List, Optional

class SlackView:
    """Base class for Slack Block Kit rendering."""

    @staticmethod
    def header(text: str) -> dict:
        return {
            "type": "header",
            "text": {"type": "plain_text", "text": text, "emoji": True}
        }

    @staticmethod
    def section(text: str) -> dict:
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text}
        }

    @staticmethod
    def divider() -> dict:
        return {"type": "divider"}

    @staticmethod
    def context(text: str) -> dict:
        return {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": text}]
        }
