"""Discord notification channel via Webhook.

Uses Discord's embed format for rich, colour-coded messages with fields
for agent metadata.  No external dependencies — HTTP is handled with
:mod:`urllib.request`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
import urllib.error
from typing import Any

from .base import Notification

logger = logging.getLogger(__name__)

# Discord embed colour mapped to notification severity (decimal int).
_SEVERITY_COLOURS: dict[str, int] = {
    "info": 0x3498DB,
    "warning": 0xF39C12,
    "error": 0xE74C3C,
    "critical": 0x992D22,
}


class DiscordNotifier:
    """Send notifications to Discord via a Webhook URL.

    Uses Discord's embed format for rich, colour-coded messages with
    fields for agent metadata.

    Args:
        webhook_url: Full Discord Webhook URL.
        username:    Bot username shown in Discord.  Defaults to
                     ``"ShipIt Agent"``.
        avatar_url:  Optional avatar image URL for the bot.
    """

    name: str = "discord"

    def __init__(
        self,
        webhook_url: str,
        username: str = "ShipIt Agent",
        avatar_url: str | None = None,
    ) -> None:
        self._webhook_url = webhook_url
        self._username = username
        self._avatar_url = avatar_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, notification: Notification) -> bool:
        """Send *notification* to Discord asynchronously."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.send_sync, notification)

    async def send_batch(
        self, notifications: list[Notification]
    ) -> list[bool]:
        """Send several notifications sequentially."""
        return [await self.send(n) for n in notifications]

    def send_sync(self, notification: Notification) -> bool:
        """Blocking send — useful when no event loop is running."""
        payload = self._build_payload(notification)
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self._webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                # Discord returns 204 No Content on success.
                return resp.status in (200, 204)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            logger.warning("Discord notification failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(self, notification: Notification) -> dict[str, Any]:
        """Build the top-level Discord webhook payload."""
        embed = self._build_embed(notification)

        payload: dict[str, Any] = {
            "username": self._username,
            "embeds": [embed],
        }
        if self._avatar_url:
            payload["avatar_url"] = self._avatar_url

        return payload

    def _build_embed(self, notification: Notification) -> dict[str, Any]:
        """Construct a Discord embed for the notification.

        Layout:
        - Title and description from the notification.
        - Colour bar mapped from severity.
        - Inline fields for each metadata entry.
        - Footer with severity and ISO timestamp.
        """
        colour = _SEVERITY_COLOURS.get(notification.severity, 0x3498DB)

        embed: dict[str, Any] = {
            "title": notification.title,
            "description": notification.message,
            "color": colour,
            "timestamp": notification.timestamp.isoformat(),
            "footer": {
                "text": f"severity: {notification.severity} | event: {notification.event}",
            },
        }

        # Metadata as inline fields.
        if notification.metadata:
            embed["fields"] = [
                {"name": str(key), "value": str(value), "inline": True}
                for key, value in notification.metadata.items()
            ]

        return embed
