"""Tests for the relocated Slack client wrapper with mocked WebClient."""

from unittest.mock import MagicMock, patch

import pytest

from legion.core.exceptions import ExternalAPIError
from legion.core.slack.config import SlackConfig
from legion.slack.client import SlackClient


@pytest.fixture()
def mock_config():
    from pydantic import SecretStr
    cfg = SlackConfig(bot_token=SecretStr("xoxb-test"), app_token=SecretStr("xapp-test"))
    return cfg


@pytest.fixture()
def client(mock_config):
    with patch("legion.slack.client.WebClient") as MockWC:
        wc = MockWC.return_value
        c = SlackClient(mock_config)
        c._client = wc
        yield c


class TestSlackClient:
    def test_create_channel(self, client):
        client._client.api_call.return_value = MagicMock(
            data={"channel": {"id": "C123"}}
        )
        cid = client.create_channel("inc-test")
        assert cid == "C123"
        client._client.api_call.assert_called_once()

    def test_post_message_returns_ts(self, client):
        client._client.api_call.return_value = MagicMock(data={"ts": "1234.5678"})
        ts = client.post_message("C123", "hello")
        assert ts == "1234.5678"

    def test_post_message_with_blocks(self, client):
        client._client.api_call.return_value = MagicMock(data={"ts": "1"})
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}]
        client.post_message("C123", "hi", blocks=blocks)
        call_kwargs = client._client.api_call.call_args
        json_payload = call_kwargs.kwargs.get("json", {})
        assert "blocks" in json_payload

    def test_api_error_raises_external_api_error(self, client):
        from slack_sdk.errors import SlackApiError

        resp = MagicMock()
        resp.__getitem__ = lambda self, key: "channel_not_found"
        resp.status_code = 404
        client._client.api_call.side_effect = SlackApiError("err", response=resp)

        with pytest.raises(ExternalAPIError) as exc_info:
            client.create_channel("bad")
        assert exc_info.value.service == "slack"

    def test_fetch_conversation_history(self, client):
        client._client.api_call.return_value = MagicMock(
            data={
                "messages": [
                    {"user": "U1", "text": "hello", "ts": "1"},
                    {"user": "U2", "text": "world", "ts": "2"},
                ]
            }
        )
        history = client.fetch_conversation_history("C123", limit=50)
        assert history.channel_id == "C123"
        assert len(history.messages) == 2
        assert history.messages[0].text == "hello"
