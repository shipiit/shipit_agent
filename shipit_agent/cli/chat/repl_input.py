"""Reading input: readline completion, the command list, and permission prompts."""

from __future__ import annotations

import sys
from typing import Any

from .agents import AGENT_TYPES
from .providers import PROVIDER_NAMES
from .style import bold, cyan, dim, yellow

try:  # readline is unix-only but ships with mac/linux Python builds
    import readline  # type: ignore

    _HAS_READLINE = True
except Exception:  # pragma: no cover
    readline = None  # type: ignore
    _HAS_READLINE = False


class InputMixin:
    """Reading input: readline completion, the command list, and permission prompts."""

    def _install_readline(self) -> None:
        if not _HAS_READLINE:
            return
        try:
            readline.set_completer_delims(" \t\n")
            readline.parse_and_bind("tab: complete")
            readline.set_completer(self._readline_completer)
        except Exception:
            pass

    def _readline_completer(self, text: str, state: int):
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = text
        stripped = line.lstrip()
        candidates: list[str] = []
        if stripped.startswith("/"):
            # First word → slash command
            parts = stripped.split(" ", 1)
            if len(parts) == 1:
                candidates = [c for c in self.SLASH_COMMANDS if c.startswith(text)]
            else:
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""
                if cmd == "/agent":
                    candidates = [t for t in AGENT_TYPES if t.startswith(arg)]
                elif cmd == "/provider":
                    candidates = [p for p in PROVIDER_NAMES if p.startswith(arg)]
        try:
            return candidates[state]
        except IndexError:
            return None

    def _print_command_dropdown(self, output) -> None:
        output(dim("─ slash commands ─"))
        rows = [
            ("/help", "show this help"),
            ("/agent <type>", f"switch agent type ({'|'.join(AGENT_TYPES)})"),
            ("/agents", "list available agent types"),
            ("/provider <name>", f"switch LLM provider ({'|'.join(PROVIDER_NAMES)})"),
            ("/model <name>", "set the model for the current provider"),
            ("/tools", "list the agent's tools"),
            ("/sources", "RAG sources from the last turn"),
            ("/index <path>", "index a file into RAG"),
            ("/rag", "show RAG stats"),
            ("/goal <obj>", "set a goal (goal/deep agents)"),
            ("/reflect on|off", "toggle reflective mode (DeepAgent)"),
            ("/verify on|off", "toggle verification mode (DeepAgent)"),
            ("/history", "print conversation history"),
            ("/clear", "clear conversation history"),
            ("/save <path>", "save the conversation as JSON"),
            ("/load <path>", "load a saved conversation"),
            ("/reset", "start a fresh session"),
            ("/quiet", "toggle event streaming visibility"),
            ("/stream on|off", "toggle typewriter streaming effect"),
            ("/info", "show agent + session info"),
            ("/exit, /quit", "leave the chat"),
        ]
        for cmd, desc in rows:
            output(f"  {cyan(cmd):28s}  {dim(desc)}")
        output(dim("tip: press <TAB> after typing / to autocomplete"))

    def _wire_permission_prompt(self) -> None:
        """Attach an interactive y/n/always prompt for `ask`-gated tools."""
        if hasattr(self.agent, "permission_callback"):
            try:
                self.agent.permission_callback = self._permission_prompt
            except Exception:
                pass  # frozen/custom agent types keep their own behavior

    def _permission_prompt(self, name: str, arguments: dict) -> Any:
        from shipit_agent.safety.hitl import console_permission_prompt

        return console_permission_prompt(always_allowed=self.always_allowed)(
            name, arguments
        )

    def _permission_prompt_legacy(self, name: str, arguments: dict) -> Any:
        from shipit_agent.safety.permissions import PermissionDecision, PermissionResult

        if name in self.always_allowed:
            return PermissionResult(
                decision=PermissionDecision.ALLOW, reason="always-allowed (session)"
            )
        args_preview = ", ".join(f"{k}={v!r}" for k, v in list(arguments.items())[:4])
        if len(args_preview) > 120:
            args_preview = args_preview[:119] + "…"
        sys.stdout.write(
            yellow(f"\n⏸ allow {bold(name)}({args_preview})? ")
            + dim("[y]es / [n]o / [a]lways: ")
        )
        sys.stdout.flush()
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("a", "always"):
            self.always_allowed.add(name)
            return PermissionResult(
                decision=PermissionDecision.ALLOW, reason="user approved (always)"
            )
        if answer in ("y", "yes"):
            return PermissionResult(
                decision=PermissionDecision.ALLOW, reason="user approved"
            )
        return PermissionResult(
            decision=PermissionDecision.DENY, reason="user declined"
        )
