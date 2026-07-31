"""`shipit browse` — computer use from the CLI.

    shipit browse "find the cheapest direct SFO→JFK flight on May 20"
    shipit browse --show "book a table for two"      # visible Chrome window
    shipit browse --start-url https://news.ycombinator.com "top story?"

Drives a real browser with the vision loop (`ComputerUseAgent`): screenshots
→ reasoning → clicks/typing/scrolling, streamed as live ⏺/⎿ tool cards.
Consent walls and popups are handled by the agent itself; accepted consent
persists across runs via a storage-state file.
"""

from __future__ import annotations

import argparse
from typing import Any

from shipit_agent.cli import ui
from shipit_agent.cli.llm import build_llm


def cmd_browse(args: argparse.Namespace) -> int:
    from shipit_agent import StreamRenderer
    from shipit_agent.computer_use import (
        ComputerUseAgent,
        PlaywrightBrowserSession,
    )

    ui.banner(
        "shipit browse",
        [
            ("Goal", args.goal[:60]),
            ("Browser", "visible window" if args.show else "headless"),
            ("Max steps", str(args.max_steps)),
        ],
        emoji="🌐",
    )
    try:
        session = PlaywrightBrowserSession.launch(
            headless=not args.show,
            viewport_size=(1280, 720),
            start_url=args.start_url,
            slow_mo=200 if args.show else 0,
            storage_state=args.storage_state,
        )
    except RuntimeError as exc:  # playwright missing → actionable message
        ui.out(ui.style(str(exc), "err"))
        return 1

    renderer = StreamRenderer(style="auto")
    try:
        agent = ComputerUseAgent(
            llm=build_llm(args.provider, args.model),
            browser=session,
            goal=args.goal,
            max_iterations=args.max_steps,
        )
        result = None
        generator = agent.stream()
        while True:
            try:
                renderer.feed(next(generator))
            except StopIteration as stop:
                result = stop.value
                break
        renderer.close()
        if args.storage_state:
            session.save_storage_state()   # consent survives the next run
        if result is not None and result.final_text:
            ui.out(ui.style(f"\n{result.final_text}", "bold"))
        return 0 if (result is None or result.status != "error") else 1
    finally:
        session.close()


def register(sub: Any) -> None:
    parser = sub.add_parser(
        "browse", help="Computer use: drive a real browser toward a goal"
    )
    parser.add_argument("goal", help="What to accomplish in the browser")
    parser.add_argument("--show", action="store_true",
                        help="visible Chrome window (slowed so you can watch)")
    parser.add_argument("--start-url", default="about:blank")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument(
        "--storage-state",
        default=".shipit_workspace/browser_state.json",
        help="cookie/consent persistence file ('' to disable)",
    )
    parser.add_argument("--provider", default=None,
                        help="vision-capable model recommended")
    parser.add_argument("--model", default=None)
    parser.set_defaults(fn=cmd_browse)
