"""`git_ops` — structured git operations for the coding agent.

First-class git instead of raw bash: every action maps to a fixed argv
(no shell, no injection surface), output is clipped head+tail, and the
risky operations are opt-in:

- read:   status, diff, log, show, blame, branch, stash_list
- write:  add, commit, checkout, stash, stash_pop
- gated:  push, reset — refused unless the tool is constructed with
          ``allow_push=True`` / ``allow_reset=True`` (or the permission
          layer approves; the deny here is defense in depth).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar

from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.formatting import clip_text

_READ_ACTIONS = {
    "status", "diff", "log", "show", "blame", "branch", "stash_list",
    "worktree_list",
}
_WRITE_ACTIONS = {
    "add", "commit", "checkout", "stash", "stash_pop",
    "worktree_add", "worktree_remove",
}
_GATED_ACTIONS = {"push", "reset"}


class GitOpsTool:
    name = "git_ops"
    description = (
        "Structured git operations: status, diff, log, show, blame, branch, "
        "add, commit, checkout, stash (push/reset are disabled by default)."
    )

    ACTIONS: ClassVar[list[str]] = sorted(
        _READ_ACTIONS | _WRITE_ACTIONS | _GATED_ACTIONS
    )

    def __init__(
        self,
        *,
        root_dir: str | Path = ".",
        allow_push: bool = False,
        allow_reset: bool = False,
        timeout_seconds: int = 60,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.allow_push = allow_push
        self.allow_reset = allow_reset
        self.timeout_seconds = timeout_seconds
        self.prompt = self.prompt_instructions = (
            "Prefer this over bash for git: status before and after changes, "
            "diff to review your edits, log/show/blame to understand history, "
            "add+commit to save work (commit requires a message)."
        )

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": self.ACTIONS},
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "File paths (diff/add/blame/checkout)",
                        },
                        "message": {"type": "string",
                                    "description": "Commit/stash message"},
                        "ref": {"type": "string",
                                "description": "Branch/commit/ref (checkout/show/log)"},
                        "staged": {"type": "boolean",
                                   "description": "diff --staged"},
                        "limit": {"type": "integer",
                                  "description": "log entry count (default 15)"},
                    },
                    "required": ["action"],
                },
            },
        }

    # ------------------------------------------------------------------
    def _git(self, *argv: str) -> tuple[int, str]:
        completed = subprocess.run(  # noqa: S603 — fixed argv, shell=False
            ["git", *argv],
            cwd=self.root_dir,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
        )
        output = (completed.stdout + completed.stderr).strip()
        return completed.returncode, output

    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput:
        action = str(kwargs.get("action", ""))
        paths = [str(p) for p in (kwargs.get("paths") or [])]
        ref = str(kwargs.get("ref", "")).strip()
        message = str(kwargs.get("message", "")).strip()
        limit = int(kwargs.get("limit") or 15)

        if action in _GATED_ACTIONS:
            allowed = self.allow_push if action == "push" else self.allow_reset
            if not allowed:
                return ToolOutput(
                    text=(f"git {action} is disabled on this tool. Construct "
                          f"GitOpsTool(allow_{action}=True) to enable it."),
                    metadata={"ok": False, "action": action, "gated": True},
                )

        argv: list[str]
        if action == "status":
            argv = ["status", "--short", "--branch"]
        elif action == "diff":
            argv = ["diff", "--stat", "--patch"]
            if kwargs.get("staged"):
                argv.insert(1, "--staged")
            argv += paths
        elif action == "log":
            argv = ["log", f"-{limit}", "--oneline", "--decorate"]
            if ref:
                argv.append(ref)
        elif action == "show":
            argv = ["show", "--stat", "--patch", ref or "HEAD"]
        elif action == "blame":
            if not paths:
                return ToolOutput(text="blame needs `paths`.",
                                  metadata={"ok": False})
            argv = ["blame", "--date=short", *paths]
        elif action == "branch":
            argv = ["branch", "--all", "--verbose"]
        elif action == "add":
            argv = ["add", "--"] + (paths or ["."])
        elif action == "commit":
            if not message:
                return ToolOutput(text="commit needs `message`.",
                                  metadata={"ok": False})
            argv = ["commit", "-m", message]
        elif action == "checkout":
            if not ref and not paths:
                return ToolOutput(text="checkout needs `ref` or `paths`.",
                                  metadata={"ok": False})
            argv = ["checkout"] + ([ref] if ref else []) + (
                ["--", *paths] if paths else [])
        elif action == "stash":
            argv = ["stash", "push"] + (["-m", message] if message else [])
        elif action == "stash_pop":
            argv = ["stash", "pop"]
        elif action == "stash_list":
            argv = ["stash", "list"]
        elif action == "worktree_list":
            argv = ["worktree", "list"]
        elif action == "worktree_add":
            # Isolated workspace on a new branch: work without
            # touching the user's tree, and let several agents run in
            # parallel. `ref` is the new worktree path; `message` (optional)
            # names the branch to create (defaults to the path's basename).
            if not ref:
                return ToolOutput(
                    text="worktree_add needs `ref` (the path for the new worktree).",
                    metadata={"ok": False},
                )
            branch = message or Path(ref).name
            argv = ["worktree", "add", "-b", branch, ref]
        elif action == "worktree_remove":
            if not ref:
                return ToolOutput(
                    text="worktree_remove needs `ref` (the worktree path).",
                    metadata={"ok": False},
                )
            argv = ["worktree", "remove", ref]
        elif action == "push":
            argv = ["push"]
        elif action == "reset":
            argv = ["reset", "--hard", ref or "HEAD"]
        else:
            return ToolOutput(
                text=f"Unknown action '{action}'. Choose: {', '.join(self.ACTIONS)}",
                metadata={"ok": False},
            )

        try:
            code, output = self._git(*argv)
        except FileNotFoundError:
            return ToolOutput(text="git is not installed / not on PATH.",
                              metadata={"ok": False})
        except subprocess.TimeoutExpired:
            return ToolOutput(text=f"git {action} timed out.",
                              metadata={"ok": False})
        status = "ok" if code == 0 else f"exit {code}"
        return ToolOutput(
            text=f"git {action} ({status}):\n{clip_text(output or '(no output)')}",
            metadata={"ok": code == 0, "action": action, "exit_code": code},
        )
