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

    from shipit_agent import ApprovalQueue

    # Deferred approvals replace the blocking prompt: side-effecting calls the
    # policy marks `ask` are queued and reviewed after the run, so the agent
    # does not stall on step one while you are away. Tools whose result the
    # agent reasons over (bash, sql) still block — see tools/contracts.py.
    queue = ApprovalQueue() if getattr(args, "defer_approvals", False) else None

    agent = Agent.for_project(
        llm=build_llm(args.provider, args.model),
        project_root=root,
        mcps=mcps,
        tools=[ConsoleAskUserTool()],
        prompt=CODE_PLAYBOOK,
        permission_mode=mode,
        approvals=queue,
        code_mode=getattr(args, "code_mode", False),
        permission_callback=None if args.yes or args.plan or queue else gated_prompt,
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
            *([("Tools", "code mode — connectors in `env`")]
              if getattr(args, "code_mode", False) else []),
            *([("Approvals", "deferred — review after the run")] if queue else []),
        ],
        emoji="🛠",
    )

    events: list[Any] = []
    answer = _run(agent, args, events)
    if not answer:
        ui.out(ui.style("(no answer produced)", "dim"))

    if queue is not None and queue.pending():
        review_pending(queue)

    if getattr(args, "share", None):
        _write_share(args.share, events, answer, agent)
    return 0


def _run(agent: Any, args: argparse.Namespace, events: list[Any]) -> str:
    """Stream the run through the chosen renderer, keeping the events."""
    style = getattr(args, "style", "modern")
    if style == "modern":
        from shipit_agent.narrate import NarratorRenderer

        renderer: Any = NarratorRenderer(model=getattr(agent.llm, "model", None))
    else:
        from shipit_agent.activity import StreamRenderer

        renderer = StreamRenderer(style=style)

    answer = ""
    for event in agent.stream(args.task):
        events.append(event)
        renderer.feed(event)
        if event.type == "run_completed":
            answer = str(event.payload.get("output", "") or "")
    renderer.close()
    return answer


def review_pending(queue: Any) -> None:
    """Walk the queued actions after the run, one decision at a time.

    This is the payoff of deferring: the whole batch is in front of you at
    once, with the work already done, instead of interrupting it one call at
    a time.
    """
    from shipit_agent.tools.contracts import ActionKind

    ui.out("")
    ui.section(f"{len(queue.pending())} action(s) awaiting your approval")
    for action in list(queue.pending()):
        ui.out("")
        ui.out(f"  {ui.style(action.title, 'bold')}")
        if action.kind_label:
            ui.out(f"  {ui.style(action.kind_label + '  ·  #' + str(action.id), 'dim')}")
        for line in action.description.splitlines()[:12]:
            ui.out(f"    {ui.style(line, 'dim')}")

        choices = "[y]es / [n]o" + ("  / [a]lways this kind" if action.tag else "")
        sys.stdout.write(ui.style(f"\n  approve? {choices}: ", "warn"))
        sys.stdout.flush()
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer.startswith("a") and action.tag:
            queue.enable_auto(
                ActionKind(action.tag, action.kind_label or action.tag), by="cli"
            )
            queue.drain(by="cli")
        elif answer.startswith("y"):
            try:
                queue.approve(action.id, by="cli")
            except Exception as exc:
                ui.out(ui.style(f"  failed: {exc}", "err"))
        else:
            queue.deny(action.id, by="cli")

    summary = queue.summary()
    ui.out("")
    ui.out(ui.style(
        f"  {summary['counts'].get('approved', 0)} approved · "
        f"{summary['counts'].get('rejected', 0)} denied", "dim"))


def _write_share(path: str, events: list[Any], answer: str, agent: Any) -> None:
    from shipit_agent.narrate.share import write_transcript

    written = write_transcript(
        path, events, model=getattr(agent.llm, "model", None)
    )
    ui.out("")
    ui.out(ui.style(f"  transcript written to {written}", "dim"))


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
    parser.add_argument("--code-mode", action="store_true",
                        help="collapse connectors into `env` bindings reachable "
                             "from execute_code (~57%% smaller prompts)")
    parser.add_argument("--defer-approvals", action="store_true",
                        help="queue side-effecting calls instead of blocking; "
                             "review them when the run finishes")
    parser.add_argument("--style", choices=["modern", "rich", "plain"],
                        default="modern",
                        help="transcript style (default: modern)")
    parser.add_argument("--share", metavar="PATH", default=None,
                        help="write the run as a standalone HTML transcript")
    parser.add_argument("--mcp", default=None,
                        help="comma-separated MCP catalog servers to attach "
                             "(e.g. playwright — lets the agent drive a browser)")
    parser.set_defaults(fn=cmd_code)
