"""`shipit code` — the coding agent, rooted in YOUR repo.

    shipit code "fix the failing test in tests/test_api.py"
    shipit code --plan "how would you add rate limiting?"   # read-only
    shipit code --yes "rename UserSvc to UserService"       # auto-accept edits

Builds an `Agent.for_project(cwd)`: project memory (SHIPIT.md/AGENTS.md),
/slash commands, checked-in permission policy, full file/shell toolbox —
with a developer playbook prompt, hardened edits (diffs + stale detection),
and live ⏺/⎿ streaming. Interactive [y]/[n]/[a]lways prompts fire for any
tool the policy marks `ask`.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from shipit_agent.cli import ui

CODE_PLAYBOOK = """
You are a senior software engineer working directly in the user's repository.

Playbook:
1. READ FIRST — locate the relevant files (glob/grep), read them fully,
   trace callers before changing signatures.
2. SMALLEST CORRECT PATCH — edit_file with exact replacements; match the
   file's existing style; no drive-by refactors.
3. VERIFY — run the project's tests/build with bash; never claim done
   without running something. If tests fail, iterate.
4. REPORT — what changed (path:line), what you ran, what passed.
""".strip()


def _permission_prompt(name: str, arguments: dict[str, Any]) -> Any:
    from shipit_agent.permissions import PermissionDecision, PermissionResult

    preview = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in list(arguments.items())[:3])
    sys.stdout.write(
        ui.style(f"\n⏸ allow {name}({preview})? ", "warn")
        + ui.style("[y]es / [n]o / [a]lways: ", "dim")
    )
    sys.stdout.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in ("y", "yes", "a", "always"):
        if answer.startswith("a"):
            _permission_prompt.always.add(name)  # type: ignore[attr-defined]
        return PermissionResult(
            decision=PermissionDecision.ALLOW, reason="user approved"
        )
    return PermissionResult(decision=PermissionDecision.DENY, reason="user declined")


_permission_prompt.always = set()  # type: ignore[attr-defined]


def cmd_code(args: argparse.Namespace) -> int:
    from shipit_agent import Agent, Guardrails
    from shipit_agent.cli.llm import build_llm

    root = os.getcwd()
    mode = "plan" if args.plan else ("acceptEdits" if args.yes else "default")

    from shipit_agent.hitl import console_permission_prompt

    gated_prompt = console_permission_prompt(
        always_allowed=_permission_prompt.always  # type: ignore[attr-defined]
    )

    mcps = []
    if getattr(args, "mcp", None):
        from shipit_agent import connect_mcp

        for name in [n.strip() for n in args.mcp.split(",") if n.strip()]:
            mcps.append(connect_mcp(name))

    from shipit_agent.hitl import ConsoleAskUserTool

    agent = Agent.for_project(
        llm=build_llm(args.provider, args.model),
        project_root=root,
        mcps=mcps,
        tools=[ConsoleAskUserTool()],
        prompt=CODE_PLAYBOOK,
        permission_mode=mode,
        permission_callback=None if args.yes or args.plan else gated_prompt,
        guardrails=Guardrails.strict(max_tool_calls=args.max_tool_calls)
        if args.guardrails == "strict"
        else Guardrails.standard(),
    )

    ui.banner(
        "shipit code",
        [
            ("Repository", root),
            ("Mode", {"plan": "plan (read-only)", "acceptEdits": "auto-accept edits",
                      "default": "ask before risky tools"}[mode]),
            ("Guardrails", args.guardrails),
        ],
        emoji="🛠",
    )
    answer = agent.run_live(args.task)
    if not answer:
        ui.out(ui.style("(no answer produced)", "dim"))
    return 0


def register(sub: Any) -> None:
    parser = sub.add_parser(
        "code", help="Coding agent rooted in the current repo"
    )
    parser.add_argument("task", help="What to build / fix / explain")
    parser.add_argument("--plan", action="store_true",
                        help="read-only: research and propose, change nothing")
    parser.add_argument("--yes", action="store_true",
                        help="auto-accept edits (no per-tool prompts)")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--guardrails", choices=["standard", "strict"],
                        default="standard")
    parser.add_argument("--max-tool-calls", type=int, default=50)
    parser.add_argument("--mcp", default=None,
                        help="comma-separated MCP catalog servers to attach "
                             "(e.g. playwright — lets the agent drive a browser)")
    parser.set_defaults(fn=cmd_code)
