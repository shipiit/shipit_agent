"""Slack actions: search, post, channels, history, threads and user lookup."""

from __future__ import annotations

from typing import Any

from shipit_agent.tools.base import ToolOutput


class _SlackActions:
    """Slack actions: search, post, channels, history, threads and user lookup."""

    def _search_messages(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _post_message(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _list_channels(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _channel_history(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _get_thread_replies(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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

    def _user_lookup(
        self, record: Any, action: str, kwargs: dict[str, Any]
    ) -> ToolOutput:
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
