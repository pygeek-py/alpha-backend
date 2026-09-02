from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings

from apps.telegram.client import TelegramClient, TelegramError


class TestTelegramClientInit:
    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_missing_token_raises(self):
        with pytest.raises(TelegramError):
            TelegramClient()

    def test_explicit_token_overrides_settings(self):
        client = TelegramClient(bot_token="explicit-token")
        assert client.bot_token == "explicit-token"


class TestSendMessage:
    def test_successful_send_returns_message_id(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 42}}
        with patch("apps.telegram.client.requests.post", return_value=mock_response) as mock_post:
            result = client.send_message(chat_id="123", text="hello")

        assert result.message_id == 42
        assert mock_post.call_args.kwargs["json"]["chat_id"] == "123"
        assert mock_post.call_args.kwargs["json"]["text"] == "hello"

    def test_network_error_raises_telegram_error(self):
        client = TelegramClient(bot_token="fake-token")
        with patch("apps.telegram.client.requests.post", side_effect=requests.ConnectionError("down")):
            with pytest.raises(TelegramError):
                client.send_message(chat_id="123", text="hello")

    def test_api_reported_failure_raises_telegram_error(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=400)
        mock_response.json.return_value = {"ok": False, "description": "chat not found"}
        with patch("apps.telegram.client.requests.post", return_value=mock_response):
            with pytest.raises(TelegramError, match="chat not found"):
                client.send_message(chat_id="123", text="hello")

    def test_non_json_response_raises_telegram_error(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=502)
        mock_response.json.side_effect = ValueError("not json")
        with patch("apps.telegram.client.requests.post", return_value=mock_response):
            with pytest.raises(TelegramError):
                client.send_message(chat_id="123", text="hello")


class TestGetUpdates:
    def test_no_updates_returns_empty_list(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"ok": True, "result": []}
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            assert client.get_updates() == []

    def test_extracts_chat_from_a_private_message(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "ok": True,
            "result": [
                {
                    "message": {
                        "chat": {"id": 6591991724, "type": "private", "username": "pygeek_py"}
                    }
                }
            ],
        }
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            chats = client.get_updates()

        assert len(chats) == 1
        assert chats[0].chat_id == "6591991724"
        assert chats[0].chat_type == "private"
        assert chats[0].name == "pygeek_py"

    def test_deduplicates_repeated_messages_from_the_same_chat(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "ok": True,
            "result": [
                {"message": {"chat": {"id": 1, "type": "private", "first_name": "A"}}},
                {"message": {"chat": {"id": 1, "type": "private", "first_name": "A"}}},
            ],
        }
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            chats = client.get_updates()

        assert len(chats) == 1

    def test_falls_back_to_first_name_when_no_username(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {
            "ok": True,
            "result": [{"message": {"chat": {"id": 1, "type": "private", "first_name": "Ada"}}}],
        }
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            chats = client.get_updates()

        assert chats[0].name == "Ada"

    def test_ignores_updates_without_a_message(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {"ok": True, "result": [{"edited_message": {}}]}
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            assert client.get_updates() == []

    def test_api_reported_failure_raises_telegram_error(self):
        client = TelegramClient(bot_token="fake-token")
        mock_response = Mock(status_code=401)
        mock_response.json.return_value = {"ok": False, "description": "Unauthorized"}
        with patch("apps.telegram.client.requests.get", return_value=mock_response):
            with pytest.raises(TelegramError, match="Unauthorized"):
                client.get_updates()

    def test_network_error_raises_telegram_error(self):
        client = TelegramClient(bot_token="fake-token")
        with patch("apps.telegram.client.requests.get", side_effect=requests.ConnectionError("down")):
            with pytest.raises(TelegramError):
                client.get_updates()
