"""The ``shipit chat`` command line: its arguments and entry point."""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import Any

from shipit_agent.stores import FileSessionStore, InMemorySessionStore

from .agents import AGENT_TYPES
from .providers import build_llm
from .repl import ChatREPL
from .style import dim, red


def build_parser() -> argparse.ArgumentParser:
    """The ``shipit-chat`` command-line parser."""
    parser = argparse.ArgumentParser(
        prog="shipit-chat",
        description="Modern interactive chat with any Shipit agent type.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              shipit chat
              shipit chat --agent agent
              shipit chat --agent deep --reflect --verify
              shipit chat --agent goal --goal "Build a todo CLI" --criteria "tests pass"
              shipit chat --rag-file docs/manual.pdf
              shipit chat --provider anthropic --session-dir ~/.shipit/sessions
        """),
    )
    parser.add_argument(
        "--agent",
        default="deep",
        choices=list(AGENT_TYPES),
        help="Agent type (default: deep)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (defaults to $SHIPIT_LLM_PROVIDER or 'bedrock')",
    )
    parser.add_argument(
        "--session-id", default=None, help="Resume a specific session id"
    )
    parser.add_argument(
        "--continue",
        dest="continue_last",
        action="store_true",
        help="Resume the most recent session from the session directory",
    )
    parser.add_argument(
        "--session-dir",
        default=None,
        help=(
            "Persist sessions to this directory (FileSessionStore). "
            "Defaults to ~/.shipit/sessions when --continue is used."
        ),
    )
    parser.add_argument(
        "--workspace",
        default=".shipit_workspace",
        help="Workspace root for the WorkspaceFilesTool",
    )
    parser.add_argument(
        "--no-builtins",
        action="store_true",
        help="Skip the regular built-in tool catalogue",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Hide intermediate event stream"
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable the typewriter streaming effect on the final answer",
    )
    parser.add_argument(
        "--rag-file",
        action="append",
        default=[],
        help="Index a file (txt/md/pdf/html) into RAG before the session starts. Repeatable.",
    )
    parser.add_argument(
        "--rag-dim",
        type=int,
        default=512,
        help="HashingEmbedder dimension when --rag-file is used (default 512)",
    )
    parser.add_argument(
        "--reflect", action="store_true", help="Enable reflective mode (DeepAgent)"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Enable verification mode (DeepAgent)"
    )
    parser.add_argument(
        "--goal", default=None, help="Goal objective (use with --agent goal)"
    )
    parser.add_argument(
        "--criteria",
        action="append",
        default=[],
        help="Goal success criterion (repeatable; use with --agent goal)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``shipit-chat``, the interactive chat; returns the exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    llm = build_llm(args.provider)

    rag = None
    if args.rag_file:
        from shipit_agent.rag import RAG, HashingEmbedder

        rag = RAG.default(embedder=HashingEmbedder(dimension=args.rag_dim))
        for path in args.rag_file:
            try:
                chunks = rag.index_file(path)
                sys.stderr.write(
                    dim(f"[chat] indexed {len(chunks)} chunks from {path}\n")
                )
            except Exception as exc:
                sys.stderr.write(red(f"[chat] failed to index {path}: {exc}\n"))

    session_dir = args.session_dir
    if args.continue_last and not session_dir:
        session_dir = str(Path.home() / ".shipit" / "sessions")

    session_store: Any
    if session_dir:
        session_store = FileSessionStore(session_dir)
    else:
        session_store = InMemorySessionStore()

    session_id = args.session_id
    if args.continue_last and not session_id:
        # Most recently modified session file wins.
        candidates = sorted(
            Path(session_dir).glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            session_id = candidates[0].stem
            sys.stderr.write(dim(f"[chat] continuing session {session_id}\n"))
        else:
            sys.stderr.write(
                dim("[chat] no previous session found — starting a new one\n")
            )

    repl = ChatREPL(
        llm=llm,
        agent_type=args.agent,
        provider=args.provider,
        rag=rag,
        workspace_root=args.workspace,
        use_builtins=not args.no_builtins,
        session_id=session_id,
        session_store=session_store,
        quiet=args.quiet,
        reflect=args.reflect,
        verify=args.verify,
        typewriter_enabled=not args.no_stream,
    )

    if args.goal:
        repl.goal_objective = args.goal
        repl.goal_criteria = args.criteria or ["Answer addresses the user's question."]
        if args.agent in {"goal", "deep"}:
            repl._rebuild_agent(print)

    return repl.run()
