"""The `shipit` CLI — modern, clean, and agent-powered.

    shipit code "fix the failing test"     coding agent in your repo
    shipit run "prompt"                    one-shot with live tool cards
    shipit chat                            interactive REPL
    shipit serve                           OpenAI-compatible API for your agent
    shipit roles | mcp | tools             catalogs
    shipit doctor | version                health / version

Package layout: `ui.py` (color/banner kit), `llm.py` (provider builder),
`commands/` (one module per command family). `main()` is the console-script
entry point (`shipit = "shipit_agent.cli:main"`).
"""

from __future__ import annotations

import argparse
import sys

from .llm import build_llm  # re-export for tests / embedding

__all__ = ["main", "build_parser", "build_llm"]


def build_parser() -> argparse.ArgumentParser:
    from .commands import browse, catalog, code, jobs, serve_cmd, simple

    parser = argparse.ArgumentParser(
        prog="shipit",
        description="shipit agent — code, run, chat, serve, and inspect your agent.",
    )
    sub = parser.add_subparsers(dest="command")
    code.register(sub)
    browse.register(sub)
    simple.register(sub)
    serve_cmd.register(sub)
    jobs.register(sub)
    catalog.register(sub)
    sub.add_parser("chat", help="Interactive REPL (flags pass through)")
    return parser


def _interactive_terminal() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Bare `shipit` on a real terminal opens the full interactive REPL —
    # bottom-pinned input, slash commands, live tool cards — like Claude
    # Code. Pipes/CI (non-TTY) keep the help text so scripts don't hang.
    if not argv and _interactive_terminal():
        from shipit_agent.chat_cli import main as chat_main

        return chat_main([])

    # Full flag passthrough for the interactive/long-running families —
    # unknown flags are forwarded untouched to their dedicated CLIs.
    if argv and argv[0] == "chat":
        from shipit_agent.chat_cli import main as chat_main

        return chat_main(argv[1:])
    if argv and argv[0] in ("autopilot", "daemon", "queue", "answer"):
        from shipit_agent.cli_autopilot import (
            run_answer_cli,
            run_autopilot_cli,
            run_daemon_cli,
            run_queue_cli,
        )

        return {
            "autopilot": run_autopilot_cli,
            "daemon": run_daemon_cli,
            "queue": run_queue_cli,
            "answer": run_answer_cli,
        }[argv[0]](argv[1:])

    parser = build_parser()
    args = parser.parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        parser.print_help()
        return 0
    return fn(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
