"""``shipit sdk`` output: the SDK's message stream, drawn live in a terminal or as JSON lines."""

from __future__ import annotations

import dataclasses
import json
import re
import time
from typing import Any, Callable

from shipit_agent.sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import ui

__all__ = ["LiveRenderer", "json_line", "printable"]

#: Control characters other than newline and tab: in text from the model or a
#: tool they could move the cursor, clear lines or retitle the terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(text: Any) -> str:
    """*text* with control characters shown as escapes instead of acting on the terminal."""
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", str(text))


def json_line(message: Any) -> str:
    """One message as a JSON line, with its type under ``"type"``."""
    body = dataclasses.asdict(message) if dataclasses.is_dataclass(message) else {"value": str(message)}
    return json.dumps({"type": type(message).__name__, **body}, default=str)


def _short(text: Any, limit: int = 160) -> str:
    flat = " ".join(printable(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class LiveRenderer:
    """Draws each message as it arrives; *write* takes text without a newline added."""

    def __init__(self, write: Callable[[str], None], *, show_hooks: bool = False) -> None:
        self.write = write
        self.show_hooks = show_hooks
        self._in_tool = False
        self._streamed = False
        self._line_open = False

    def feed(self, message: Any) -> None:
        if isinstance(message, StreamEvent):
            self._stream(message.event)
        elif isinstance(message, AssistantMessage):
            self._assistant(message)
        elif isinstance(message, UserMessage):
            self._results(message)
        elif isinstance(message, RateLimitEvent):
            due = message.rate_limit_info.get("resets_at")
            when = f", retrying at {time.strftime('%H:%M:%S', time.localtime(due))}" if due else ", retrying"
            self._line(ui.style(f"⏳ rate limited{when}", "dim"))
        elif isinstance(message, SystemMessage):
            self._system(message)
        elif isinstance(message, ResultMessage):
            self._result(message)

    def _line(self, text: str) -> None:
        if self._line_open:
            self.write("\n")
            self._line_open = False
        self.write(text + "\n")

    def _end_line(self) -> None:
        if self._line_open:
            self.write("\n")
            self._line_open = False

    def _stream(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "message_start":
            self._streamed = True
        elif kind == "content_block_start" and event.get("content_block", {}).get("type") == "tool_use":
            if self._line_open:
                self.write("\n")
            self.write(ui.style(f"⚙ {printable(event['content_block'].get('name', ''))} ", "bold"))
            self._in_tool = self._line_open = True
        elif kind == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                self.write(printable(delta.get("text", "")))
                self._line_open = True
            elif delta.get("type") == "input_json_delta" and self._in_tool:
                self.write(ui.style(printable(delta.get("partial_json", "")), "dim"))
        elif kind == "content_block_stop" and self._in_tool:
            self._in_tool = False
            self._end_line()
        elif kind == "message_stop" and self._line_open:
            self._end_line()

    def _assistant(self, message: AssistantMessage) -> None:
        if message.parent_tool_use_id:
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    self._line(ui.style(f"  ↳ sub-agent ⚙ {printable(block.name)} {_short(json.dumps(block.input), 100)}", "dim"))
                elif isinstance(block, TextBlock):
                    self._line(ui.style(f"  ↳ sub-agent: {_short(block.text)}", "dim"))
            return
        if self._streamed:
            return  # already drawn from the stream events
        for block in message.content:
            if isinstance(block, TextBlock):
                self._line(printable(block.text))
            elif isinstance(block, ToolUseBlock):
                self._line(ui.style(f"⚙ {printable(block.name)} {_short(json.dumps(block.input), 120)}", "bold"))

    def _results(self, message: UserMessage) -> None:
        if not isinstance(message.content, list):
            return
        indent = "    " if message.parent_tool_use_id else "  "
        for block in message.content:
            if isinstance(block, ToolResultBlock):
                mark, tone = ("✗", "err") if block.is_error else ("✓", "ok")
                self._line(indent + ui.style(f"{mark} {_short(block.content, 140)}", tone))

    def _system(self, message: SystemMessage) -> None:
        data = message.data
        if message.subtype == "init":
            servers = ", ".join(data.get("mcp_servers") or []) or "none"
            self._line(ui.style(f"▶ {data.get('model') or 'default model'} · {len(data.get('tools') or [])} tools · MCP: {servers}", "dim"))
        elif message.subtype == "task_progress":
            usage = data.get("usage") or {}
            self._line(ui.style(f"  ↳ sub-agent: {usage.get('tool_uses', 0)} tool calls, {usage.get('total_tokens', 0):,} tokens", "dim"))
        elif message.subtype == "api_retry":
            self._line(ui.style(f"↻ retrying the model call ({data.get('reason', 'error')})", "dim"))
        elif message.subtype == "compact_boundary":
            self._line(ui.style("⋯ older conversation summarised to fit the context", "dim"))
        elif message.subtype.startswith("hook_") and self.show_hooks:
            outcome = f" ({data.get('outcome')})" if message.subtype == "hook_response" else ""
            self._line(ui.style(f"  hook {data.get('hook_event')}: {data.get('hook_name')}{outcome}", "dim"))

    def _result(self, message: ResultMessage) -> None:
        usage = message.usage or {}
        tokens = int(usage.get("prompt_tokens", 0) or 0) + int(usage.get("completion_tokens", 0) or 0)
        cache = int(usage.get("cache_read_input_tokens", 0) or 0)
        cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "cost unknown"
        ok = message.subtype == "success"
        status = ui.style("✓ done" if ok else f"✗ {message.subtype}", "ok" if ok else "err")
        parts = [status, f"{message.num_turns} turns", f"{tokens:,} tokens", cost, f"{message.duration_ms / 1000:.1f}s"]
        if cache:
            parts.insert(3, f"{cache:,} read from cache")
        self._line("")
        self._line(" · ".join(parts))
        for error in message.errors:
            self._line(ui.style(printable(error), "err"))
