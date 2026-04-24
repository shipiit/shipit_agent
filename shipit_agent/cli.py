from __future__ import annotations

import argparse
import json
import sys

from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shipit",
        description="Shipit Agent — run a one-shot prompt or open an interactive chat.",
    )
    sub = parser.add_subparsers(dest="command")

    # `shipit run "..."` (also the default when no subcommand is given).
    run_parser = sub.add_parser(
        "run", help="Run a one-shot prompt and print the result."
    )
    run_parser.add_argument("prompt", nargs="?", default="Hello from shipit_agent")
    run_parser.add_argument(
        "--system-prompt", default="You are Shipit, a clean and capable agent runtime."
    )
    run_parser.add_argument(
        "--json", action="store_true", help="Print the full result as JSON."
    )

    # `shipit chat` — modern multi-agent interactive REPL.
    sub.add_parser("chat", help="Open an interactive chat with any agent type.")

    # Backwards-compatible top-level args (for `shipit "prompt"` without `run`).
    parser.add_argument("prompt", nargs="?", default=None)
    parser.add_argument(
        "--system-prompt", default="You are Shipit, a clean and capable agent runtime."
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the full result as JSON."
    )
    return parser


def _run_one_shot(*, prompt: str, system_prompt: str, as_json: bool) -> int:
    agent = Agent(llm=SimpleEchoLLM(), prompt=system_prompt, name="shipit")
    result = agent.run(prompt)

    if as_json:
        print(
            json.dumps(
                {
                    "output": result.output,
                    "events": [
                        {
                            "type": event.type,
                            "message": event.message,
                            "payload": event.payload,
                        }
                        for event in result.events
                    ],
                },
                indent=2,
            )
        )
    else:
        print(result.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Route `shipit chat ...` to the dedicated chat REPL — pass remaining
    # args through so flags like --agent / --rag-file / --provider keep
    # working.
    if argv and argv[0] == "chat":
        from shipit_agent.chat_cli import main as chat_main

        return chat_main(argv[1:])

    # Route long-running / daemon / queue / answer subcommands to their module.
    if argv and argv[0] in ("autopilot", "daemon", "queue", "answer"):
        from shipit_agent.cli_autopilot import (
            run_answer_cli,
            run_autopilot_cli,
            run_daemon_cli,
            run_queue_cli,
        )

        dispatch = {
            "autopilot": run_autopilot_cli,
            "daemon": run_daemon_cli,
            "queue": run_queue_cli,
            "answer": run_answer_cli,
        }
        return dispatch[argv[0]](argv[1:])

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run" or args.prompt is not None:
        prompt = args.prompt or "Hello from shipit_agent"
        return _run_one_shot(
            prompt=prompt,
            system_prompt=args.system_prompt,
            as_json=args.json,
        )

    # No subcommand and no positional prompt — print help.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
