"""Human-in-the-loop approval — one reusable console prompt for any agent.

Wire it into ANY agent (library, `shipit chat`, `shipit code`) so tools the
permission policy marks ``ask`` pause for a real human decision::

    from shipit_agent import Agent, console_permission_prompt
    from shipit_agent.permissions import PermissionEngine

    agent = Agent.with_builtins(
        llm=llm,
        permissions=PermissionEngine(ask=["bash", "write_file", "git_ops"]),
        permission_callback=console_permission_prompt(),
    )

The prompt renders `⏸ allow bash(command='rm dist')? [y]es / [n]o / [a]lways`
— **always** persists for the process, **no** denies with a reason the model
can react to. Fully injectable (``input_fn``/``output``) for tests and TUIs.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from .permissions import PermissionDecision, PermissionResult


def format_call_preview(name: str, arguments: dict[str, Any], limit: int = 100) -> str:
    preview = ", ".join(
        f"{k}={str(v)[:40]!r}" for k, v in list(arguments.items())[:4]
    )
    if len(preview) > limit:
        preview = preview[: limit - 1] + "…"
    return f"{name}({preview})"


def console_permission_prompt(
    *,
    always_allowed: set[str] | None = None,
    input_fn: Callable[[], str] | None = None,
    output: Callable[[str], None] | None = None,
) -> Callable[[str, dict[str, Any]], PermissionResult]:
    """Build a ``permission_callback`` that asks the human on the console.

    ``always_allowed`` is shared, so several agents (or a REPL session) can
    honor the same [a]lways decisions. ``input_fn``/``output`` default to
    stdin/stdout but are injectable for TUIs and tests.
    """
    approved_always: set[str] = always_allowed if always_allowed is not None else set()

    def _default_output(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    write = output or _default_output
    read = input_fn or (lambda: input())

    def prompt(name: str, arguments: dict[str, Any]) -> PermissionResult:
        if name in approved_always:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="always-allowed (session)",
            )
        # ── Claude-Code-style approval card ──────────────────────────
        # Full multi-line preview of what will run (commands are shown in
        # their entirety, not truncated), then an explicit numbered menu.
        title = name.replace("_", " ").title()
        write(f"\n\x1b[1m{title}\x1b[0m\n\n")
        for key, value in list(arguments.items())[:6]:
            text = str(value)
            if len(text) > 4000:
                text = text[:4000] + "…"
            if "\n" in text or len(text) > 80:
                indented = "\n".join("  " + line for line in text.splitlines())
                write(f"  \x1b[2m{key}:\x1b[0m\n{indented}\n")
            else:
                write(f"  \x1b[2m{key}:\x1b[0m {text}\n")
        write("\n\x1b[33mThis tool call requires approval\x1b[0m\n")
        write("\nDo you want to proceed?\n")
        write("  1. Yes\n")
        write(f"  2. Yes, and don't ask again for: \x1b[1m{name}\x1b[0m\n")
        write("  3. No\n")
        write("▸ ")
        try:
            answer = read().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "3"
        if answer in ("2", "a", "always"):
            approved_always.add(name)
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="user approved (always)",
            )
        if answer in ("1", "y", "yes"):
            return PermissionResult(
                decision=PermissionDecision.ALLOW, reason="user approved"
            )
        return PermissionResult(
            decision=PermissionDecision.DENY, reason="user declined"
        )

    return prompt


class ConsoleAskUserTool:
    """`ask_user` that ACTUALLY asks on the terminal.

    The builtin `ask_user` emits an `interactive_request` event for UIs to
    handle. On the CLI there is a human right there — this variant prints
    the question (with numbered options), reads the answer from stdin, and
    returns it so the run continues immediately. The CLI swaps it in over
    the builtin (same name → last-write-wins in the tool merge).
    """

    name = "ask_user"
    description = "Ask the user a clarifying question and wait for their answer."

    def __init__(self, *, input_fn: Any = None, output: Any = None) -> None:
        self._read = input_fn or (lambda: input())
        self._write = output or (lambda t: (sys.stdout.write(t), sys.stdout.flush()))
        self.prompt = self.prompt_instructions = (
            "Use only when missing information blocks safe progress. Ask ONE "
            "specific question; offer options when they exist."
        )

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"},
                                    "description": "Optional numbered choices"},
                    },
                    "required": ["question"],
                },
            },
        }

    def run(self, context: Any, **kwargs: Any) -> Any:
        from shipit_agent.tools.base import ToolOutput

        question = str(kwargs.get("question", "")).strip()
        options = [str(o) for o in (kwargs.get("options") or [])]
        self._write(f"\n❓ {question}\n")
        for i, option in enumerate(options, 1):
            self._write(f"   {i}. {option}\n")
        self._write("you ▸ ")
        try:
            answer = self._read().strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        # numeric pick → the option text
        if answer.isdigit() and options and 1 <= int(answer) <= len(options):
            answer = options[int(answer) - 1]
        if not answer:
            answer = "(no answer provided — proceed with your best judgment)"
        return ToolOutput(text=answer,
                          metadata={"question": question, "answered": True})
