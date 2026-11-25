"""``monitor``: the Claude Agent SDK's Monitor, as a background command under bash's rules.

A watch runs a command in the background; each line it prints goes to the
watch's log, which the model reads as it would any background job's, and it
hears when the watch ends. The command goes through the bash tool's own
checks, environment, sandbox and job table, so a rule or sandbox that stops a
bash command stops the same command here, and ``task_stop`` stops a watch.
Every watch has a deadline. WebSocket sources are not supported.
"""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

from shipit_agent.tools.base import ToolContext, ToolOutput

if TYPE_CHECKING:
    from .bash_tool import BashTool

DEFAULT_TIMEOUT_MS = 300_000
#: The SDK accepts up to an hour but holds every watch to 30 minutes.
MAX_TIMEOUT_MS = 1_800_000
MIN_TIMEOUT_MS = 1_000


class MonitorTool:
    """Watch a command's output in the background, until it ends or its deadline."""

    read_only = False

    def __init__(self, bash_tool: BashTool, *, name: str = "monitor") -> None:
        self._bash = bash_tool
        self.name = name
        self.description = (
            "Run a command in the background and watch its output: each line it prints is "
            "logged as it happens. Use for logs, test watchers or anything you wait on."
        )
        self.prompt_instructions = (
            "Give a short description. Read the watch's log file for its lines so far; "
            "you are told when it ends. Stop it with task_stop when you no longer need it."
        )

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": {
                "command": {"type": "string", "description": "Shell command; each line it prints is an event"},
                "description": {"type": "string", "description": "A short description of the watch"},
                "timeout_ms": {"type": "integer", "description": "Deadline in milliseconds (default 300000)"},
            }, "required": ["command", "description"]},
        }}

    def assess_command(self, arguments: dict[str, Any]) -> Any:
        """The bash tool's verdict on the command: blocked, risky or fine."""
        return self._bash.assess_command(arguments)

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        command = str(kwargs.get("command") or "")
        description = str(kwargs.get("description") or "").strip()
        if kwargs.get("ws") is not None:
            if command:
                return ToolOutput.error("Pass exactly one source: `command` (WebSocket sources are not supported).")
            return ToolOutput.error("WebSocket sources are not supported; watch a `command` instead.")
        if not command.strip():
            return ToolOutput.error("Pass `command`: the shell command to watch.")
        if not description:
            return ToolOutput.error("Pass `description`: a few words on what the watch is for.")
        try:
            self._bash._refuse_no_op(command)
            self._bash._validate_command(command)
            wrapped = self._bash._shell_argv(command)
        except Exception as error:  # a refused command is the model's to fix, not a crash
            return ToolOutput.error(f"Command rejected: {error}")
        timeout_ms = _clamp(kwargs.get("timeout_ms"))
        started = self._bash._run_background(command, self._bash._resolve_dir(None), argv=wrapped.argv)
        job_id = str(started.metadata["job_id"])
        self._bash.background_jobs[job_id]["description"] = description
        self._stop_at_deadline(job_id, timeout_ms / 1000)
        body = {"taskId": job_id, "timeoutMs": timeout_ms, "persistent": False}
        return ToolOutput(text=json.dumps(body), metadata={**started.metadata, "monitor": True, "timeout_ms": timeout_ms})

    def _stop_at_deadline(self, job_id: str, seconds: float) -> None:
        timer = threading.Timer(seconds, self._bash.kill_job, args=(job_id,))
        timer.daemon = True
        timer.start()


def _clamp(value: Any) -> int:
    try:
        wanted = int(value) if value is not None else DEFAULT_TIMEOUT_MS
    except (TypeError, ValueError):
        wanted = DEFAULT_TIMEOUT_MS
    return max(MIN_TIMEOUT_MS, min(MAX_TIMEOUT_MS, wanted))
