from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.connector_base import HTTPConnectorToolBase
from .prompt import SLACK_PROMPT


class SlackTool(HTTPConnectorToolBase):
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
            return self._not_connected_output()
        action = str(kwargs.get("action", "search_messages"))
        if action == "search_messages":
            data = self._unwrap_ok(
                self._request_json(
                    record=record,
                    method="GET",
                    path="/search.messages",
                    query={
                        "query": str(kwargs.get("query", "")),
                        "count": int(kwargs.get("limit", 10)),
                    },
                )
            )
            matches = data.get("messages", {}).get("matches", [])
            lines = [self._format_message(item) for item in matches]
            return ToolOutput(
                text="\n".join(lines) if lines else "No Slack messages found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": matches,
                    "count": len(matches),
                },
            )
        if action == "post_message":
            payload = {"channel": kwargs.get("channel"), "text": kwargs.get("text", "")}
            thread_ts = str(kwargs.get("thread_ts", "")).strip()
            if thread_ts:
                payload["thread_ts"] = thread_ts
            data = self._unwrap_ok(
                self._request_json(
                    record=record, method="POST", path="/chat.postMessage", body=payload
                )
            )
            return ToolOutput(
                text=f"Slack message posted to {kwargs.get('channel')}",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "result": data,
                },
            )
        if action == "list_channels":
            data = self._unwrap_ok(
                self._request_json(
                    record=record,
                    method="GET",
                    path="/conversations.list",
                    query={"limit": int(kwargs.get("limit", 10))},
                )
            )
            channels = data.get("channels", [])
            return ToolOutput(
                text="\n".join(
                    f"{item.get('name', '?')} ({item.get('id', '?')})"
                    for item in channels
                ),
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": channels,
                    "count": len(channels),
                },
            )
        if action == "channel_history":
            channel = str(kwargs.get("channel", "")).strip()
            if not channel:
                return ToolOutput(
                    text="channel is required for channel_history.",
                    metadata={"provider": self.provider, "action": action},
                )
            data = self._unwrap_ok(
                self._request_json(
                    record=record,
                    method="GET",
                    path="/conversations.history",
                    query={"channel": channel, "limit": int(kwargs.get("limit", 10))},
                )
            )
            messages = data.get("messages", [])
            lines = [
                self._format_message({**item, "channel_id": channel})
                for item in messages
            ]
            return ToolOutput(
                text="\n\n".join(lines)
                if lines
                else f"No Slack history found for channel {channel}.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "channel": channel,
                    "items": messages,
                    "count": len(messages),
                },
            )
        if action == "get_thread_replies":
            channel = str(kwargs.get("channel", "")).strip()
            thread_ts = str(kwargs.get("thread_ts", "")).strip()
            if not channel or not thread_ts:
                return ToolOutput(
                    text="channel and thread_ts are required for get_thread_replies.",
                    metadata={"provider": self.provider, "action": action},
                )
            data = self._unwrap_ok(
                self._request_json(
                    record=record,
                    method="GET",
                    path="/conversations.replies",
                    query={
                        "channel": channel,
                        "ts": thread_ts,
                        "limit": int(kwargs.get("limit", 20)),
                    },
                )
            )
            replies = data.get("messages", [])
            lines = [
                self._format_message({**item, "channel_id": channel})
                for item in replies
            ]
            return ToolOutput(
                text="\n\n".join(lines)
                if lines
                else f"No replies found for thread {thread_ts}.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "channel": channel,
                    "thread_ts": thread_ts,
                    "items": replies,
                    "count": len(replies),
                },
            )
        if action == "user_lookup":
            email = str(kwargs.get("email", "")).strip()
            query = str(kwargs.get("user_query", "")).strip().lower()
            if email:
                data = self._unwrap_ok(
                    self._request_json(
                        record=record,
                        method="GET",
                        path="/users.lookupByEmail",
                        query={"email": email},
                    )
                )
                user = data.get("user", {})
                return ToolOutput(
                    text=self._format_user(user)
                    if user
                    else f"No Slack user found for {email}.",
                    metadata={
                        "provider": self.provider,
                        "connected": True,
                        "action": action,
                        "user": user,
                    },
                )
            data = self._unwrap_ok(
                self._request_json(
                    record=record,
                    method="GET",
                    path="/users.list",
                    query={"limit": int(kwargs.get("limit", 50))},
                )
            )
            members = data.get("members", [])
            if query:
                members = [
                    item
                    for item in members
                    if query in str(item.get("name", "")).lower()
                    or query in str(item.get("real_name", "")).lower()
                    or query
                    in str(item.get("profile", {}).get("real_name", "")).lower()
                    or query in str(item.get("profile", {}).get("email", "")).lower()
                ]
            lines = [self._format_user(item) for item in members]
            return ToolOutput(
                text="\n".join(lines) if lines else "No Slack users found.",
                metadata={
                    "provider": self.provider,
                    "connected": True,
                    "action": action,
                    "items": members,
                    "count": len(members),
                },
            )
        raise ValueError(f"Unsupported Slack action: {action}")
