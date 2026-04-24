"""CLI subcommands for Autopilot and the scheduler daemon.

Usage::

    shipit autopilot "<goal>" [--criteria "..."] [--max-hours H] [--jsonl]
    shipit autopilot --resume <run_id>
    shipit daemon   [--tick 5] [--queue ~/.shipit_agent/queue.json]
    shipit queue    add  "<run_id>" "<objective>" [--criteria "..."] [--max-seconds N]
    shipit queue    list
    shipit queue    remove <run_id>

Each subcommand renders events in Claude-Desktop-style live TUI by
default. Pass ``--jsonl`` for machine-readable event output (good for
piping into ``jq``) or ``--plain`` for colourless text.

The CLI is LLM-agnostic: the caller is expected to have already set up
provider credentials in the environment (e.g. ``OPENAI_API_KEY``). The
LLM factory is resolved from ``SHIPIT_LLM`` env — the same pattern the
rest of the library uses.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from shipit_agent.askuser_channel import all_entries, pending_questions, write_answer
from shipit_agent.autopilot import Autopilot, BudgetPolicy, default_heartbeat_stderr
from shipit_agent.deep.goal_agent import Goal
from shipit_agent.live_renderer import render_stream
from shipit_agent.scheduler_daemon import SchedulerDaemon


# ─────────────────────── entry points ───────────────────────


def run_autopilot_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="shipit autopilot", description="Run a long-running Autopilot goal."
    )
    p.add_argument(
        "objective", nargs="?", help="The goal objective. Required unless --resume."
    )
    p.add_argument(
        "--criteria",
        action="append",
        default=[],
        help="One success criterion (repeatable).",
    )
    p.add_argument("--run-id", default=None, help="Stable id for checkpoint/resume.")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Continue the given --run-id from its checkpoint.",
    )
    p.add_argument(
        "--max-hours", type=float, default=None, help="Override wall-clock cap (hours)."
    )
    p.add_argument(
        "--max-tools", type=int, default=None, help="Override tool-call cap."
    )
    p.add_argument("--max-tokens", type=int, default=None, help="Override token cap.")
    p.add_argument(
        "--max-dollars", type=float, default=None, help="Override dollar cap."
    )
    p.add_argument(
        "--heartbeat",
        type=float,
        default=60.0,
        help="Heartbeat interval seconds (default 60).",
    )
    p.add_argument("--format", choices=["tui", "jsonl", "plain"], default="tui")
    p.add_argument(
        "--checkpoint-dir", default=None, help="Override checkpoint directory."
    )
    args = p.parse_args(argv)

    if not args.resume and not args.objective:
        p.error("objective is required unless --resume is given")

    llm = _resolve_llm()
    if llm is None:
        print(
            "Error: set SHIPIT_LLM=<provider> (openai|anthropic|bedrock|ollama|groq|gemini).",
            file=sys.stderr,
        )
        return 2

    autopilot = Autopilot(
        llm=llm,
        goal=Goal(
            objective=args.objective or "(resumed)",
            success_criteria=list(args.criteria),
        ),
        budget=_build_budget(args),
        checkpoint_dir=args.checkpoint_dir,
        heartbeat_every_seconds=args.heartbeat,
        on_heartbeat=default_heartbeat_stderr if args.format == "tui" else None,
    )

    events = autopilot.stream(run_id=args.run_id, resume=args.resume)
    result = render_stream(events, fmt=args.format)
    return 0 if result and result.get("status") in ("completed", "partial") else 1


def run_daemon_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="shipit daemon", description="Run the Autopilot goal queue daemon."
    )
    p.add_argument(
        "--tick",
        type=float,
        default=5.0,
        help="Seconds between queue scans (default 5).",
    )
    p.add_argument(
        "--queue",
        default=None,
        help="Queue file path (default ~/.shipit_agent/autopilot-queue.json).",
    )
    p.add_argument(
        "--once", action="store_true", help="Drain one pending goal then exit."
    )
    args = p.parse_args(argv)

    llm_factory = _resolve_llm_factory()
    if llm_factory is None:
        print("Error: set SHIPIT_LLM=<provider>.", file=sys.stderr)
        return 2

    daemon = SchedulerDaemon(
        llm_factory=llm_factory,
        queue_path=args.queue,
        tick_seconds=args.tick,
        on_heartbeat=_stderr_event,
    )
    if args.once:
        result = daemon.run_once()
        if result is None:
            print("(queue empty)")
            return 0
        print(f"{result.run_id}: {result.status} ({result.iterations} iters)")
        return 0 if result.status in ("completed", "partial") else 1

    daemon.run_forever()
    return 0


def run_answer_cli(argv: list[str]) -> int:
    """Answer an outstanding ask_user_async question — the async reply path."""
    p = argparse.ArgumentParser(
        prog="shipit answer",
        description="Answer an Autopilot run's outstanding ask_user_async question.",
    )
    p.add_argument(
        "run_id", help="The Autopilot run id whose question you're answering."
    )
    p.add_argument(
        "answer",
        nargs="?",
        help="The answer text. Omit to list pending questions instead.",
    )
    p.add_argument(
        "--index",
        type=int,
        default=None,
        help="Which pending question (by index) to answer.",
    )
    args = p.parse_args(argv)

    pending = pending_questions(args.run_id)

    if args.answer is None:
        # Status mode — show pending + answered history.
        if not all_entries(args.run_id):
            print(f"(no questions recorded for run_id={args.run_id})")
            return 0
        for i, entry in enumerate(all_entries(args.run_id)):
            tag = "ANSWERED" if entry.answered() else "PENDING "
            print(f"[{i:02d}] {tag}  {entry.question}")
            if entry.context:
                print(f"          context: {entry.context}")
            if entry.choices:
                print(f"          choices: {', '.join(entry.choices)}")
            if entry.answered():
                print(f"          answer:  {entry.answer}")
        return 0

    if not pending:
        print(f"No pending question on run_id={args.run_id}.")
        return 1

    ok = write_answer(args.run_id, args.answer, index=args.index)
    if not ok:
        print("Could not record answer — index out of range or already answered.")
        return 1
    print(
        f"Answer recorded for run_id={args.run_id}. "
        f"Resume with: shipit autopilot --resume --run-id {args.run_id}"
    )
    return 0


def run_queue_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="shipit queue", description="Manage the Autopilot goal queue."
    )
    sub = p.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="Add a goal to the queue.")
    add.add_argument("run_id")
    add.add_argument("objective")
    add.add_argument("--criteria", action="append", default=[])
    add.add_argument("--max-seconds", type=int, default=None)
    add.add_argument("--max-tools", type=int, default=None)

    sub.add_parser("list", help="List queued goals.")
    rm = sub.add_parser("remove", help="Remove a queued goal.")
    rm.add_argument("run_id")

    p.add_argument("--queue", default=None)
    args = p.parse_args(argv)

    daemon = SchedulerDaemon(llm_factory=lambda: None, queue_path=args.queue)

    if args.action == "add":
        budget = {}
        if args.max_seconds is not None:
            budget["max_seconds"] = args.max_seconds
        if args.max_tools is not None:
            budget["max_tool_calls"] = args.max_tools
        daemon.enqueue(
            run_id=args.run_id,
            objective=args.objective,
            success_criteria=args.criteria,
            budget=budget,
        )
        print(f"Queued {args.run_id}.")
        return 0
    if args.action == "list":
        for e in daemon.list_queue():
            print(f"{e.run_id}  [{e.status:<7}]  {e.objective[:80]}")
        return 0
    if args.action == "remove":
        ok = daemon.remove(args.run_id)
        print("removed." if ok else "not found.")
        return 0 if ok else 1
    return 1


# ─────────────────────── helpers ───────────────────────


def _build_budget(args: argparse.Namespace) -> BudgetPolicy:
    budget = BudgetPolicy()
    if args.max_hours is not None:
        budget.max_seconds = max(60.0, args.max_hours * 3600)
    if args.max_tools is not None:
        budget.max_tool_calls = max(1, args.max_tools)
    if args.max_tokens is not None:
        budget.max_tokens = max(1000, args.max_tokens)
    if args.max_dollars is not None:
        budget.max_dollars = max(0.1, args.max_dollars)
    return budget


def _resolve_llm() -> Any | None:
    """Load an LLM instance from the ``SHIPIT_LLM`` env, or None if unset.

    Deliberately tolerant — if the user hasn't installed the provider
    SDK, we fall back to ``SimpleEchoLLM`` so they can smoke-test the
    pipeline before wiring real credentials.
    """
    name = os.environ.get("SHIPIT_LLM", "").lower()
    try:
        if name in ("openai", "oai"):
            from shipit_agent.llms import OpenAIChat

            return OpenAIChat(model=os.environ.get("SHIPIT_MODEL", "gpt-4o-mini"))
        if name in ("anthropic", "claude"):
            from shipit_agent.llms import AnthropicChat

            return AnthropicChat(
                model=os.environ.get("SHIPIT_MODEL", "claude-sonnet-4-5")
            )
        if name == "bedrock":
            from shipit_agent.llms import BedrockChat

            return BedrockChat(
                model=os.environ.get(
                    "SHIPIT_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
                )
            )
        if name == "ollama":
            from shipit_agent.llms import OllamaChat

            return OllamaChat(model=os.environ.get("SHIPIT_MODEL", "llama3.3"))
        # Default / fallback — the in-process echo LLM is safe to use
        # without any credentials and is useful for dry-running the loop.
        from shipit_agent.llms import SimpleEchoLLM

        return SimpleEchoLLM()
    except Exception as err:  # noqa: BLE001
        print(f"[warn] could not resolve LLM={name!r}: {err}", file=sys.stderr)
        return None


def _resolve_llm_factory():
    llm = _resolve_llm()
    if llm is None:
        return None
    return lambda: llm


def _stderr_event(payload: dict[str, Any]) -> None:
    # Daemon heartbeat sink — one line to stderr.
    kind = payload.get("kind") or "heartbeat"
    sys.stderr.write(f"[daemon {kind}] {payload}\n")
