"""Thin Telegram Bot API client (ARCHITECTURE.md S9): raw HTTP via
`requests` (already a project dependency), not the heavier python-telegram-
bot framework -- sendMessage is the only call this project needs.

Never imported by anything outside this app; apps/telegram/services.py is
the sole caller. No parse_mode is set -- plain text avoids an entire class
of HTML/Markdown-escaping bugs from token symbols or narrative names that
could contain special characters.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger("alpha.telegram")

BASE_URL = "https://api.telegram.org"
TIMEOUT_SECONDS = 10


class TelegramError(Exception):
    """Raised when a Telegram Bot API call fails for any reason (network
    error, bad token, invalid chat id, API-reported failure). Callers decide
    retry/logging policy -- this module just reports honestly."""


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: int


@dataclass(frozen=True)
class DiscoveredChat:
    """A chat the bot has received a message from, per getUpdates -- how a
    user finds their numeric chat_id without hand-decoding raw JSON (PRD
    S38 point 2, "Connect the bot to the platform")."""

    chat_id: str
    chat_type: str
    name: str


class TelegramClient:
    """Real Bot API client."""

    def __init__(self, bot_token: str | None = None):
        self.bot_token = bot_token or settings.TELEGRAM_BOT_TOKEN
        if not self.bot_token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not configured")

    def send_message(self, *, chat_id: str, text: str) -> TelegramSendResult:
        url = f"{BASE_URL}/bot{self.bot_token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise TelegramError(f"Telegram sendMessage request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramError(
                f"Telegram sendMessage returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

        if not payload.get("ok"):
            description = payload.get("description", f"HTTP {response.status_code}")
            raise TelegramError(f"Telegram sendMessage failed: {description}")

        return TelegramSendResult(message_id=payload["result"]["message_id"])

    def get_updates(self) -> list[DiscoveredChat]:
        """Recent messages sent TO the bot, deduplicated by chat. Telegram
        only retains updates until they're fetched via this (non-webhook)
        polling method, and only once the user has messaged the bot at
        least once since the last fetch -- both are true limitations to
        surface to the user, not paper over."""
        url = f"{BASE_URL}/bot{self.bot_token}/getUpdates"
        try:
            response = requests.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise TelegramError(f"Telegram getUpdates request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramError(
                f"Telegram getUpdates returned a non-JSON response (HTTP {response.status_code})"
            ) from exc

        if not payload.get("ok"):
            description = payload.get("description", f"HTTP {response.status_code}")
            raise TelegramError(f"Telegram getUpdates failed: {description}")

        seen: dict[str, DiscoveredChat] = {}
        for update in payload.get("result", []):
            message = update.get("message") or update.get("channel_post")
            if not message:
                continue
            chat = message["chat"]
            name = chat.get("username") or chat.get("first_name") or chat.get("title") or "unknown"
            chat_id = str(chat["id"])
            seen[chat_id] = DiscoveredChat(
                chat_id=chat_id, chat_type=chat.get("type", "unknown"), name=name
            )
        return list(seen.values())
