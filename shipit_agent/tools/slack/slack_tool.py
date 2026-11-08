"""The ``slack`` tool: search Slack messages and post Slack messages."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase

from .actions import _SlackActions
from .prompt import SLACK_PROMPT


class SlackTool(_SlackActions, HTTPConnectorToolBase):
    """The ``slack`` tool: search Slack messages and post Slack messages."""
    provider = "slack"

    def __init__(
        self,
        *,
        credential_key: str = "slack",
        credential_store=None,
        name: str = "slack",
        description: str = "Search Slack messages and post Slack messages.",
        prompt: str | None = None,
    ) -> None:
        super().__init__(
            credential_key=credential_key, credential_store=credential_store
        )
        self.name = name
        self.description = description
        self.prompt = prompt or SLACK_PROMPT
        self.prompt_instructions = "Use this for Slack message discovery, channel history, thread replies, user lookup, and posting to channels."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "search_messages",
                                "post_message",
                                "list_channels",
                                "channel_history",
                                "get_thread_replies",
                                "user_lookup",
                            ],
                            "default": "search_messages",
                        },
                        "query": {"type": "string"},
                        "channel": {
                            "type": "string",
                            "description": "Slack channel ID for posting, history, or thread lookups",
                        },
                        "text": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                        "thread_ts": {
                            "type": "string",
                            "description": "Slack thread timestamp for replies or threaded posting",
                        },
                        "email": {
                            "type": "string",
                            "description": "User email for user_lookup",
                        },
                        "user_query": {
                            "type": "string",
                            "description": "Name, display name, or email fragment for Slack user lookup",
                        },
                    },
                    "required": ["action"],
                },
            },
        }

    def _base_url(self, record):
        return "https://slack.com/api"

    def _unwrap_ok(self, data: dict[str, Any]) -> dict[str, Any]:
        if data.get("ok", True):
            return data
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown_error')}")

    def _channel_name(self, payload: dict[str, Any]) -> str:
        channel = payload.get("channel")
        if isinstance(channel, dict):
            return str(channel.get("name", channel.get("id", "?")))
        return str(
            payload.get("channel_name")
            or payload.get("channel_id")
            or payload.get("channel")
            or "?"
        )

    def _format_message(self, item: dict[str, Any]) -> str:
        channel_name = self._channel_name(item)
        user = str(item.get("username") or item.get("user") or "?")
        text = str(item.get("text", "")).strip()
        ts = str(item.get("ts", "?"))
        thread_ts = str(item.get("thread_ts", "")).strip()
        suffix = f" [thread {thread_ts}]" if thread_ts and thread_ts != ts else ""
        return f"{channel_name} | {user} | {ts}{suffix}\n{text}"

    def _format_user(self, item: dict[str, Any]) -> str:
        profile = item.get("profile", {})
        email = profile.get("email", "?")
        real_name = (
            item.get("real_name") or profile.get("real_name") or item.get("name", "?")
        )
        return f"{real_name} ({item.get('id', '?')}) <{email}>"

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        record = self._get_record(context)
        if record is None:
            return self._not_connected_output(context)
        action = str(kwargs.get("action", "search_messages"))
        handlers = {
            "search_messages": self._search_messages,
            "post_message": self._post_message,
            "list_channels": self._list_channels,
            "channel_history": self._channel_history,
            "get_thread_replies": self._get_thread_replies,
            "user_lookup": self._user_lookup,
        }
        handler = handlers.get(action)
        if handler is not None:
            return handler(record, action, kwargs)
        raise ValueError(f"Unsupported Slack action: {action}")
