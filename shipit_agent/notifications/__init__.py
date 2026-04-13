"""Notification Hub — multi-channel agent event notifications.

Provides a unified interface for sending agent lifecycle notifications
to Slack, Discord, Telegram, or any custom channel implementing the
:class:`Notifier` protocol.

Example::

    from shipit_agent.notifications import (
        NotificationManager, SlackNotifier, DiscordNotifier,
    )

    manager = NotificationManager([
        SlackNotifier(webhook_url="https://hooks.slack.com/..."),
        DiscordNotifier(webhook_url="https://discord.com/api/webhooks/..."),
    ])

    agent = Agent.with_builtins(llm=llm, hooks=manager.as_hooks())
"""

from __future__ import annotations

from .base import Notification, Notifier
from .discord import DiscordNotifier
from .manager import NotificationManager
from .slack import SlackNotifier
from .telegram import TelegramNotifier

__all__ = [
    "DiscordNotifier",
    "Notification",
    "NotificationManager",
    "Notifier",
    "SlackNotifier",
    "TelegramNotifier",
]
