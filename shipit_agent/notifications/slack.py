"""Slack notification channel via Incoming Webhook.

Uses Slack's `Block Kit`_ for rich, colour-coded messages.  No external
dependencies — HTTP is handled with :mod:`urllib.request`.

.. _Block Kit: https://api.slack.com/block-kit
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

# Slack attachment colour mapped to notification severity.
_SEVERITY_COLOURS: dict[str, str] = {
    "info": "#3498db",  # blue
    "warning": "#f1c40f",  # yellow
    "error": "#e74c3c",  # red
    "critical": "#992d22",  # dark red
}


class SlackNotifier:
    """Send notifications to Slack via an Incoming Webhook URL.

    Uses Slack's Block Kit for rich formatting with colour-coded severity
    bars and structured metadata fields.

    Args:
        webhook_url: Full Slack Incoming Webhook URL.
        channel:     Optional channel override (only works with legacy
                     webhooks).
        username:    Bot username shown in Slack.  Defaults to
                     ``"ShipIt Agent"``.
    """

    name: str = "slack"

    def __init__(
        self,
        webhook_url: str,
        channel: str | None = None,
        username: str = "ShipIt Agent",
    ) -> None:
        self._webhook_url = webhook_url
        self._channel = channel
        self._username = username

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, notification: Notification) -> bool:
        """Send *notification* to Slack asynchronously.

        Delegates to :meth:`send_sync` inside a thread so the event loop
        is never blocked.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.send_sync, notification)

    async def send_batch(self, notifications: list[Notification]) -> list[bool]:
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
                return resp.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            logger.warning("Slack notification failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(self, notification: Notification) -> dict[str, Any]:
        """Build the top-level Slack message payload."""
        colour = _SEVERITY_COLOURS.get(notification.severity, "#3498db")
        blocks = self._build_blocks(notification)

        payload: dict[str, Any] = {
            "username": self._username,
            "attachments": [
                {
                    "color": colour,
                    "blocks": blocks,
                }
            ],
        }
        if self._channel:
            payload["channel"] = self._channel

        return payload

    def _build_blocks(self, notification: Notification) -> list[dict[str, Any]]:
        """Construct Block Kit blocks for the notification.

        Layout:
        1. Header block with the title.
        2. Section block with the message body.
        3. Fields section with metadata key/value pairs (if any).
        4. Context block with the timestamp.
        """
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": notification.title,
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": notification.message,
                },
            },
        ]

        # Metadata fields — rendered as a two-column grid.
        if notification.metadata:
            fields = [
                {
                    "type": "mrkdwn",
                    "text": f"*{key}:* {value}",
                }
                for key, value in notification.metadata.items()
            ]
            blocks.append({"type": "section", "fields": fields})

        # Footer with timestamp.
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f":clock1: {notification.timestamp.isoformat()} "
                            f"| severity: *{notification.severity}*"
                        ),
                    }
                ],
            }
        )

        return blocks
