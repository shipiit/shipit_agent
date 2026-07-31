"""`shipit serve` — expose the agent as an OpenAI-compatible API."""

from __future__ import annotations

import argparse
import os
from typing import Any

from shipit_agent.cli import ui
from shipit_agent.cli.llm import build_agent


def cmd_serve(args: argparse.Namespace) -> int:
    from shipit_agent.serve import AgentServer

    agent = build_agent(args)
    server = AgentServer(agent, model_name=args.name, api_key=args.api_key)
    shown = "localhost" if args.host in ("127.0.0.1", "localhost") else args.host
    ui.banner(
        "shipit agent is serving",
        [
            ("OpenAI-compatible API", f"http://{shown}:{args.port}/v1"),
            ("Chat endpoint", f"http://{shown}:{args.port}/v1/chat/completions"),
            ("Health", f"http://{shown}:{args.port}/health"),
            ("Model id", args.name),
            ("Auth", "Bearer <api-key>" if args.api_key else "none (local)"),
        ],
    )
    ui.out("  Point any OpenAI SDK at the base URL above.")
    ui.out(ui.style("  To stop: press Ctrl+C.", "dim"))
    server.serve_forever(host=args.host, port=args.port)
    return 0


def register(sub: Any) -> None:
    parser = sub.add_parser(
        "serve", help="Expose the agent as an OpenAI-compatible API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8399)
    parser.add_argument("--name", default="shipit", help="served model id")
    parser.add_argument("--api-key", default=os.environ.get("SHIPIT_API_KEY"),
                        help="require this Bearer key (default: open on loopback)")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--role", default=None)
    parser.add_argument("--guardrails", choices=["standard", "strict"], default=None)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--mcp", default=None,
                        help="comma-separated MCP catalog servers to attach")
    parser.set_defaults(fn=cmd_serve)
