"""A compact transcript in the shape Claude Code prints: one line per tool
call, a short result under it, and the model's words in between.

    ⏺ I'll look at the SDK's query module.

    ⏺ Search(def run_messages, path: shipit_agent)
      ⎿  Found 1 line
    ⏺ Read(shipit_agent/sdk/query.py)
      ⎿  Read 160 lines
    ⏺ Bash(ls shipit_agent/sdk)
      ⎿  __init__.py
         ask_user.py
         … +9 lines

    ⏺ query.py builds the agent and streams its messages.
                                           9,120 tokens · $0.0300 · claude-sonnet-5-5

Long tool output is never printed whole: a few lines, then how many more.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from shipit_agent.core.models import AgentEvent

__all__ = ["CompactRenderer", "display_name", "result_lines"]

#: Tool names as people know them from Claude Code.
_NAMES = {
    "read_file": "Read", "grep_files": "Search", "glob_files": "Search", "bash": "Bash",
    "edit_file": "Update", "multi_edit": "Update", "write_file": "Write", "notebook_edit": "Update",
    "open_url": "Fetch", "web_search": "Web Search", "todo": "Update Todos", "sub_agent": "Task",
    "ask_user": "Ask", "load_skill": "Skill", "search_tools": "Tool Search", "tool_search": "Tool Search",
}
#: The argument that says what a call is about, in order of preference.
_PRIMARY = ("path", "file_path", "command", "pattern", "url", "query", "task", "goal", "name")
#: Where a tool's main argument is not the first of those.
_PRIMARY_FOR = {"grep_files": "pattern", "glob_files": "pattern"}
_COUNTED = {"read_file": ("Read", "line"), "grep_files": ("Found", "line"), "glob_files": ("Found", "file")}
_OWN_MESSAGE = frozenset({"edit_file", "multi_edit", "write_file", "notebook_edit", "todo", "load_skill"})


def display_name(tool: str) -> str:
    """``read_file`` → ``Read``; an MCP tool ``github__get_issue`` → ``github - get_issue (MCP)``."""
    if tool in _NAMES:
        return _NAMES[tool]
    server, sep, name = tool.partition("__")
    return f"{server} - {name} (MCP)" if sep and name else tool


def call_label(tool: str, arguments: dict[str, Any]) -> str:
    """``Read(src/app.py)``, ``Search(TODO, path: src)``."""
    preferred = _PRIMARY_FOR.get(tool)
    primary = preferred if arguments.get(preferred) not in (None, "") else next(
        (key for key in _PRIMARY if arguments.get(key) not in (None, "")), None)
    parts = [_clip(str(arguments[primary]), 80)] if primary else []
    extras = [key for key in arguments if key != primary and arguments[key] not in (None, "", [], {})]
    parts += [f"{key}: {_clip(str(arguments[key]), 40)}" for key in extras[:2]]
    return f"{display_name(tool)}({', '.join(parts)})"


def result_lines(tool: str, output: str, *, max_lines: int = 3) -> list[str]:
    """What to show under a finished call: a count, the tool's own message, or the first lines."""
    lines = [line for line in (output or "").splitlines() if line.strip()]
    if tool == "bash":
        lines = _shell_lines(lines)
    if not lines:
        return ["(No output)"]
    if tool in _COUNTED:
        verb, noun = _COUNTED[tool]
        if tool != "read_file" and lines[0].lower().startswith("no "):
            return [_clip(lines[0], 160)]
        return [f"{verb} {len(lines)} {noun}{'' if len(lines) == 1 else 's'}"]
    if tool in _OWN_MESSAGE:
        return [_clip(lines[0], 160)]
    shown = [_clip(line, 160) for line in lines[:max_lines]]
    if len(lines) > max_lines:
        shown.append(f"… +{len(lines) - max_lines} lines")
    return shown


def _shell_lines(lines: list[str]) -> list[str]:
    """bash's output without its framing; the exit code only when it is not 0."""
    if not lines or not lines[0].startswith("exit_code:"):
        return lines
    code = lines[0].partition(":")[2].strip()
    body = [line for line in lines[1:] if line.strip() not in ("stdout:", "stderr:", "(no output)")]
    return ([f"Exit code {code}"] if code != "0" else []) + body


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split()) if "\n" in text else text.rstrip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CompactRenderer:
    """Feed it a run's events; it prints the compact transcript as they arrive."""

    def __init__(
        self,
        *,
        write: Callable[[str], Any] | None = None,
        color: bool | None = None,
        max_lines: int = 3,
        show_footer: bool = True,
        model: str = "",
    ) -> None:
        self._write = write or sys.stdout.write
        self.color = sys.stdout.isatty() if color is None else color
        self.max_lines = max_lines
        self.show_footer = show_footer
        self.model = model
        self._calls: dict[str, tuple[str, dict[str, Any]]] = {}
        self._streaming = False  # text deltas of the current response are being printed
        self._said: list[str] = []  # texts already printed, so none is printed twice

    # -- output ----------------------------------------------------------------

    def _paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text

    def _line(self, text: str = "") -> None:
        self._end_stream()
        self._write(text + "\n")

    def _end_stream(self) -> None:
        if self._streaming:
            self._streaming = False
            self._write("\n")

    def _say(self, text: str) -> None:
        text = text.strip()
        if not text or text in self._said:
            return
        self._said.append(text)
        first, *rest = text.splitlines()
        self._line()
        self._line(f"{self._paint('⏺', '37')} {first}")
        for line in rest:
            self._line(f"  {line}")

    def _block(self, label: str, lines: list[str], *, failed: bool = False) -> None:
        bullet = self._paint("⏺", "31" if failed else "32")
        self._line(f"{bullet} {self._paint(label, '1')}")
        for index, line in enumerate(lines):
            lead = "  ⎿  " if index == 0 else "     "
            self._line(self._paint(lead, "2") + (self._paint(line, "31") if failed else line))

    # -- events ----------------------------------------------------------------

    def feed(self, event: AgentEvent) -> None:
        handler = getattr(self, f"_on_{event.type}", None)
        if handler is not None:
            handler(event.payload)

    def close(self) -> None:
        self._end_stream()

    def _on_text_delta(self, payload: dict[str, Any]) -> None:
        chunk = str(payload.get("chunk") or "")
        if not chunk:
            return
        if not self._streaming:
            self._write("\n" + self._paint("⏺", "37") + " ")
            self._streaming = True
        self._write(chunk)

    def _on_assistant_message(self, payload: dict[str, Any]) -> None:
        text = str(payload.get("content") or "")
        if self._streaming:
            # Already printed as it streamed.
            self._end_stream()
            self._said.append(text.strip())
            return
        self._say(text)

    def _on_reasoning_completed(self, payload: dict[str, Any]) -> None:
        thought = str(payload.get("content") or "").strip().splitlines()
        if thought:
            self._line(self._paint(f"✻ {_clip(thought[0], 100)}", "2"))

    def _on_tool_called(self, payload: dict[str, Any]) -> None:
        self._calls[str(payload.get("call_id"))] = (str(payload.get("tool")), dict(payload.get("arguments") or {}))

    def _on_tool_completed(self, payload: dict[str, Any]) -> None:
        tool, arguments = self._calls.pop(str(payload.get("call_id")), (str(payload.get("tool")), {}))
        failed = bool(payload.get("error"))
        output = str(payload.get("output") or payload.get("error") or "")
        lines = result_lines(tool, output, max_lines=self.max_lines) if not failed else self._error_lines(output)
        self._block(call_label(tool, arguments), lines, failed=failed)

    def _on_tool_failed(self, payload: dict[str, Any]) -> None:
        tool, arguments = self._calls.pop(str(payload.get("call_id")), (str(payload.get("tool")), {}))
        self._block(call_label(tool, arguments), self._error_lines(str(payload.get("error") or "")), failed=True)

    def _on_tool_denied(self, payload: dict[str, Any]) -> None:
        tool, arguments = self._calls.pop(str(payload.get("call_id")), (str(payload.get("tool")), {}))
        self._block(call_label(tool, arguments), [f"Denied: {_clip(str(payload.get('reason') or ''), 160)}"],
                    failed=True)

    def _on_tool_arguments_rejected(self, payload: dict[str, Any]) -> None:
        tool = str(payload.get("tool"))
        self._block(call_label(tool, dict(payload.get("arguments") or {})),
                    self._error_lines(str(payload.get("reason") or "invalid arguments")), failed=True)

    def _error_lines(self, text: str) -> list[str]:
        lines = [line for line in text.splitlines() if line.strip()] or ["failed"]
        return [f"Error: {_clip(lines[0], 160)}", *[_clip(line, 160) for line in lines[1:2]]]

    def _on_final_answer(self, payload: dict[str, Any]) -> None:
        self._say(str(payload.get("content") or ""))

    def _on_context_compacted(self, payload: dict[str, Any]) -> None:
        self._line(self._paint("✻ Compacted the conversation to stay within the context window", "2"))

    def _on_llm_retry(self, payload: dict[str, Any]) -> None:
        self._line(self._paint(f"✻ Retrying the model call ({payload.get('reason', 'error')})", "2"))

    def _on_model_fallback(self, payload: dict[str, Any]) -> None:
        self._line(self._paint(f"✻ Switched to {payload.get('to_model')} after {payload.get('from_model')} failed",
                               "33"))

    def _on_run_failed(self, payload: dict[str, Any]) -> None:
        self._block("Error", [f"{payload.get('error_type', 'Error')}: {_clip(str(payload.get('error', '')), 200)}"],
                    failed=True)

    def _on_run_completed(self, payload: dict[str, Any]) -> None:
        if not self._said:
            self._say(str(payload.get("output") or ""))
        if not self.show_footer:
            return
        summary = payload.get("summary") or {}
        tokens = int((summary.get("usage") or payload.get("usage") or {}).get("total_tokens", 0) or 0)
        parts = [f"{tokens:,} tokens"] if tokens else []
        cost = summary.get("estimated_cost_usd")
        if cost:
            parts.append(f"${cost:.4f}")
        if self.model:
            parts.append(self.model)
        if parts:
            self._line()
            self._line(self._paint(" · ".join(parts).rjust(78), "2"))
