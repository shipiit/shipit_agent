"""Telegram notification channel via Bot API.

Uses Telegram's ``sendMessage`` endpoint with MarkdownV2 formatting for
clean, readable agent status updates.  No external dependencies — HTTP
is handled with :mod:`urllib.request`.

Telegram Bot API reference:
https://core.telegram.org/bots/api#sendmessage
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
import urllib.error
from typing import Any

from .base import Notification

logger = logging.getLogger(__name__)

# Emoji prefix for each severity level.
_SEVERITY_EMOJI: dict[str, str] = {
    "info": "\u2139\ufe0f",  # information
    "warning": "\u26a0\ufe0f",  # warning
    "error": "\u274c",  # cross mark
    "critical": "\U0001f6a8",  # rotating light
}

# Characters that must be escaped in Telegram MarkdownV2.
_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


class TelegramNotifier:
    """Send notifications to Telegram via the Bot API.

    Uses Telegram's ``sendMessage`` API with MarkdownV2 formatting for
    clean, readable agent status updates.

    Args:
        bot_token: Telegram Bot API token (from BotFather).
        chat_id:   Target chat / group / channel ID.
    """

    name: str = "telegram"

    _BASE_URL = "https://api.telegram.org"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, notification: Notification) -> bool:
        """Send *notification* to Telegram asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.send_sync, notification)

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
        """Send several notifications sequentially."""
        return [await self.send(n) for n in notifications]

    def send_sync(self, notification: Notification) -> bool:
        """Blocking send — useful when no event loop is running."""
        url = f"{self._BASE_URL}/bot{self._bot_token}/sendMessage"
        text = self._format_markdown(notification)
        payload: dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return body.get("ok", False)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            logger.warning("Telegram notification failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def _format_markdown(self, notification: Notification) -> str:
        """Build a MarkdownV2-formatted message for *notification*.

        Layout::

            <emoji> *Title*
            ─────────────────
            Message body

            *key:* value
            *key:* value

            _timestamp — severity_
        """
        emoji = _SEVERITY_EMOJI.get(notification.severity, "\u2139\ufe0f")
        title = self._escape(notification.title)
        message = self._escape(notification.message)

        lines: list[str] = [
            f"{emoji} *{title}*",
            self._escape("─" * 20),
            message,
        ]

        # Metadata fields.
        if notification.metadata:
            lines.append("")  # blank line
            for key, value in notification.metadata.items():
                lines.append(f"*{self._escape(str(key))}:* {self._escape(str(value))}")

        # Footer.
        ts = self._escape(notification.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"))
        severity = self._escape(notification.severity)
        lines.append("")
        lines.append(f"_{ts} \\| {severity}_")

        return "\n".join(lines)

    @staticmethod
    def _escape(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        return _ESCAPE_RE.sub(r"\\\1", text)
