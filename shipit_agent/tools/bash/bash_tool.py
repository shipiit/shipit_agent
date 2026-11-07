"""The ``bash`` tool: run a shell command inside the local project root with basic safety checks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.formatting import clip_text
from shipit_agent.tools.subprocess_env import build_tool_env

from .command_risk import CommandVerdict, assess_command, command_segments
from .conservative import (
    DEFAULT_ALLOWED_PREFIXES,
    DEFAULT_BLOCKED_SUBSTRINGS,
    check_conservative,
)
from .jobs import BackgroundJobsMixin, BashJobTool, is_long_running
from .prompt import BASH_PROMPT
from .runner import StillRunning, run_command


class BashTool(BackgroundJobsMixin):
    """The ``bash`` tool: run any shell command in the project root.

    What may run without approval is decided per command by
    :mod:`.command_risk` at the permission gate; a command still running at
    its timeout continues as a background job (see :mod:`.runner`).
    """
    def __init__(
        self,
        *,
        root_dir: str | Path = "/tmp",
        name: str = "bash",
        description: str = (
            "Run a shell command in the project root: tests, builds, git, package "
            "managers, scripts. Risky commands (deleting, publishing, writing "
            "outside the project) need approval."
        ),
        prompt: str | None = None,
        # Two minutes, as in Claude Code; a command still running then keeps
        # going in the background instead of being killed.
        default_timeout: float = 120.0,
        # Allow up to 600s so real test suites and builds aren't killed
        # mid-run. Raised from 120s.
        max_timeout: float = 600.0,
        allowed_command_prefixes: list[str] | None = None,
        blocked_substrings: list[str] | None = None,
        #: A full shell (any command, redirections, heredocs, substitution)
        #: is the default; what may run without approval is decided by
        #: :mod:`.command_risk` at the permission gate. Pass an explicit
        #: ``allowed_command_prefixes``, or ``unrestricted=False``, for the
        #: conservative mode: a first-token allowlist and no redirection.
        unrestricted: bool | None = None,
        #: The child shell gets a scrubbed environment (PATH, HOME, locale,
        #: TERM, TMPDIR and similar) so host secrets are not readable with
        #: ``printenv``. ``env_allowlist`` passes named host variables through,
        #: ``extra_env`` sets explicit values (e.g. ``{"HOME": workspace}``),
        #: and ``inherit_env=True`` restores the full host environment.
        env_allowlist: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
        inherit_env: bool = False,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.name = name
        self.description = description
        self.prompt = prompt or BASH_PROMPT
        self.prompt_instructions = (
            "Run shell commands in the project: inspect, search, test, build. "
            "Commands that delete, publish, or reach outside the project need "
            "approval; prefer the file tools for reading and editing files."
        )
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout
        self.unrestricted = (
            allowed_command_prefixes is None if unrestricted is None else unrestricted
        )
        self.env_allowlist = list(env_allowlist or [])
        self.extra_env = dict(extra_env or {})
        self.inherit_env = inherit_env
        #: Live background jobs, id → {process, log_path, command}, for the
        #: companion poll/kill tool.
        self.background_jobs: dict[str, dict[str, Any]] = {}
        self.allowed_command_prefixes = list(
            allowed_command_prefixes or DEFAULT_ALLOWED_PREFIXES
        )
        #: Patterns refused outright. The defaults guard the conservative
        #: mode; the full shell checks the classifier's "blocked" level
        #: instead, so the tool and the permission gate agree. A caller's own
        #: list applies in both modes.
        self._custom_blocklist = blocked_substrings is not None
        self.blocked_substrings = list(blocked_substrings or DEFAULT_BLOCKED_SUBSTRINGS)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "The shell command to run, e.g. `pytest -q`. Never a placeholder "
                                "such as `:` or `true`: to plan or explain, write text instead."
                            ),
                        },
                        "timeout": {
                            "type": "number",
                            "description": (
                                "Seconds to wait before moving the command to the "
                                "background (default 120, max 600)"
                            ),
                        },
                        "working_directory": {
                            "type": "string",
                            "description": "Optional relative working directory under the project root",
                        },
                        "background": {
                            "type": "boolean",
                            "description": (
                                "Run the command detached, write logs to a file, "
                                "and return immediately. Use for dev servers, "
                                "watchers, and other commands that don't exit. "
                                "Common long-running commands (npm run dev, "
                                "next dev, vite, uvicorn, etc.) are auto-detected "
                                "and backgrounded even if this flag isn't set."
                            ),
                        },
                    },
                    "required": ["command"],
                },
            },
        }

    def _resolve_dir(self, relative_path: str | None) -> Path:
        target = self.root_dir if not relative_path else (self.root_dir / relative_path)
        candidate = target.resolve()
        if self.root_dir not in candidate.parents and candidate != self.root_dir:
            raise ValueError("Working directory escapes project root")
        return candidate

    def _validate_command(self, command: str) -> None:
        normalized = command.strip()
        if not normalized:
            raise ValueError("Command must not be empty")
        lowered = normalized.lower()
        if self.unrestricted:
            verdict = assess_command(normalized, root=self.root_dir)
            if verdict.level == "blocked":
                raise ValueError("; ".join(verdict.reasons))
        if self._custom_blocklist or not self.unrestricted:
            for blocked in self.blocked_substrings:
                if blocked in lowered:
                    raise ValueError(f"Blocked shell command pattern: {blocked}")

        if not self.unrestricted:
            check_conservative(normalized, self.allowed_command_prefixes)

    @staticmethod
    def _refuse_no_op(command: str) -> None:
        """A command that does nothing costs a turn; models send one as a placeholder.

        Kept out of :meth:`_validate_command`, which says whether a command is
        safe to run: a no-op is safe, only pointless.
        """
        if command.strip() and all(part.strip() in (":", "true") for part in command_segments(command.strip())):
            raise ValueError(
                "this command does nothing. Put the command you want to run in "
                "`command`; to plan or think, write text instead of calling bash."
            )

    def assess_command(self, arguments: dict[str, Any]) -> CommandVerdict:
        """How risky the call's command is; the permission gate decides on it."""
        return assess_command(str(arguments.get("command", "")), root=self.root_dir)

    def run(self, context: ToolContext, **kwargs) -> ToolOutput:
        command = str(kwargs.get("command", ""))
        # A validation failure is a result the model can fix, not a crash: a
        # raised exception escapes the tool and can take the whole run down.
        try:
            self._refuse_no_op(command)
            self._validate_command(command)
        except ValueError as exc:
            return ToolOutput(
                text=f"Command rejected: {exc}",
                metadata={"ok": False, "error": "invalid_command", "command": command},
            )
        timeout = min(
            max(float(kwargs.get("timeout", self.default_timeout)), 1.0),
            self.max_timeout,
        )
        cwd = self._resolve_dir(kwargs.get("working_directory"))
        background = bool(kwargs.get("background"))
        if background or is_long_running(command):
            return self._run_background(command, cwd)
        outcome = run_command(
            command, cwd=cwd, env=self._child_env(), timeout=timeout
        )
        if isinstance(outcome, StillRunning):
            return self._adopt_timed_out(command, cwd, outcome)
        # Clip long logs to head + tail so a noisy command can't flood the
        # model's context while still keeping the error/exit at the very end.
        output = clip_text(outcome.stdout.strip())
        error = clip_text(outcome.stderr.strip())
        lines: list[str] = [f"exit_code: {outcome.exit_code}"]
        if output:
            lines.append("stdout:")
            lines.append(output)
            if output != outcome.stdout.strip():
                lines.append(f"(full stdout: {outcome.stdout_path})")
        if error:
            lines.append("stderr:")
            lines.append(error)
            if error != outcome.stderr.strip():
                lines.append(f"(full stderr: {outcome.stderr_path})")
        if not output and not error:
            lines.append("(no output)")
        return ToolOutput(
            text="\n".join(lines),
            metadata={
                "command": command,
                "cwd": str(cwd),
                "exit_code": outcome.exit_code,
                "stdout": outcome.stdout,
                "stderr": outcome.stderr,
                "stdout_path": str(outcome.stdout_path),
                "stderr_path": str(outcome.stderr_path),
                "duration_seconds": round(outcome.duration, 4),
            },
        )

    def _child_env(self) -> dict[str, str]:
        return build_tool_env(
            allowlist=self.env_allowlist,
            extra_env=self.extra_env,
            inherit=self.inherit_env,
        )


__all__ = ["BashJobTool", "BashTool"]
