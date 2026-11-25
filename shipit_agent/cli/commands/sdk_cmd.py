"""``shipit sdk "prompt"``: run one prompt through ``shipit_agent.sdk`` and watch it live.

    shipit sdk "Why does tests/test_api.py fail?" --tools Read,Grep,Bash
    shipit sdk "Summarise README.md" --model claude-haiku-5-5 --json

Text streams as it is written and tool calls as their arguments are written.
A tool call that needs approval is asked about on the terminal; with no
terminal it is refused.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

__all__ = ["cmd_sdk", "options_from", "parse_args", "register"]


def _list(value: str | None) -> list[str]:
    """Comma-separated items; a comma inside a rule's parentheses stays in the rule."""
    items, current, depth = [], "", 0
    for char in value or "":
        depth += (char == "(") - (char == ")")
        if char == "," and depth <= 0:
            items.append(current)
            current, depth = "", 0
        else:
            current += char
    items.append(current)
    return [item.strip() for item in items if item.strip()]


def _ask_on_terminal(tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
    """Approve a call on the terminal; refuse when there is no one to ask."""
    from shipit_agent.sdk import PermissionResultAllow, PermissionResultDeny

    if not sys.stdin.isatty():
        return PermissionResultDeny(message="No one is at the terminal to approve this call.")
    detail = tool_input.get("command") or tool_input.get("path") or tool_input.get("url") or ""
    answer = input(f"\nAllow {tool_name} {detail}? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        return PermissionResultAllow()
    return PermissionResultDeny(message="The user refused this call.")


def options_from(args: argparse.Namespace) -> Any:
    """The ``AgentOptions`` for these command-line arguments."""
    from shipit_agent.sdk import AgentOptions

    tools = _list(args.tools)
    return AgentOptions(
        model=args.model,
        tools=tools or None,
        allowed_tools=_list(args.allow),
        disallowed_tools=_list(args.deny),
        permission_mode=args.mode,
        can_use_tool=_ask_on_terminal,
        max_turns=args.max_turns,
        max_budget_usd=args.budget,
        cache_ttl=args.cache_ttl,
        cwd=args.cwd,
        include_partial_messages=not args.json and not args.no_stream,
        include_hook_events=args.show_hooks,
        forward_subagent_text=args.subagent_text,
    )


def cmd_sdk(args: argparse.Namespace) -> int:
    """Run the prompt; exit 0 when it finished, 1 when it stopped short."""
    from shipit_agent.cli.sdk_render import LiveRenderer, json_line
    from shipit_agent.sdk import ResultMessage, query

    options = options_from(args)
    renderer = LiveRenderer(lambda text: (sys.stdout.write(text), sys.stdout.flush()), show_hooks=args.show_hooks)

    async def run() -> int:
        code = 1
        async for message in query(prompt=args.prompt, options=options):
            if args.json:
                print(json_line(message), flush=True)
            else:
                renderer.feed(message)
            if isinstance(message, ResultMessage):
                code = 0 if message.subtype == "success" else 1
        return code

    return asyncio.run(run())


def register(sub: Any) -> None:
    """Add the ``sdk`` sub-command to the CLI."""
    parser = sub.add_parser("sdk", help="Run a prompt through the SDK layer and watch it live")
    parser.add_argument("prompt")
    parser.add_argument("--model", default=None, help="model id (default: from the environment)")
    parser.add_argument("--tools", default=None, help="comma-separated tools, SDK names work: Read,Grep,Bash")
    parser.add_argument("--allow", default=None, help="comma-separated rules that need no approval: 'Bash(pytest *)'")
    parser.add_argument("--deny", default=None, help="comma-separated rules to refuse: 'Bash(rm *)'")
    parser.add_argument("--mode", default="default", choices=["default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"],
                        help="permission mode (default asks on the terminal)")
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--budget", type=float, default=None, help="stop at this estimated cost in US dollars")
    parser.add_argument("--cache-ttl", choices=["5m", "1h"], default=None, help="prompt cache lifetime on Claude models")
    parser.add_argument("--cwd", default=None, help="the folder the tools work in (default: here)")
    parser.add_argument("--json", action="store_true", help="print each message as a JSON line")
    parser.add_argument("--no-stream", action="store_true", help="show whole messages instead of live text")
    parser.add_argument("--show-hooks", action="store_true", help="show hook events")
    parser.add_argument("--subagent-text", action="store_true", help="show sub-agents' text, not only their tool calls")
    parser.set_defaults(fn=cmd_sdk)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """``shipit sdk`` arguments, parsed without running anything."""
    parser = argparse.ArgumentParser(prog="shipit")
    register(parser.add_subparsers(dest="command"))
    return parser.parse_args(["sdk", *argv])
