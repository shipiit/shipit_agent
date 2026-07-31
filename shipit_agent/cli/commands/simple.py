"""Simple commands: run, doctor, version."""

from __future__ import annotations

import argparse
import json
from typing import Any

from shipit_agent.cli.llm import build_agent


def _agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", default=None,
                        help="bedrock | openai | anthropic | ollama | echo")
    parser.add_argument("--model", default=None, help="model id override")
    parser.add_argument("--role", default=None,
                        help="prebuilt sector role (see `shipit roles`)")
    parser.add_argument("--guardrails", choices=["standard", "strict"],
                        default=None, help="enable content guardrails")
    parser.add_argument("--project-root", default=None,
                        help="base dir for file/shell tools (default: cwd)")


def cmd_run(args: argparse.Namespace) -> int:
    agent = build_agent(args)
    if args.json:
        result = agent.run(args.prompt)
        print(json.dumps(
            {"output": result.output, "summary": result.summary()}, indent=2))
    else:
        agent.run_live(args.prompt)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    agent = build_agent(args)
    print(agent.doctor())
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    import shipit_agent

    print(getattr(shipit_agent, "__version__", "unknown"))
    return 0


def register(sub: Any) -> None:
    run_p = sub.add_parser("run", help="One-shot prompt with live tool cards")
    run_p.add_argument("prompt")
    run_p.add_argument("--json", action="store_true",
                       help="print result + metrics as JSON")
    _agent_options(run_p)
    run_p.set_defaults(fn=cmd_run)

    doctor_p = sub.add_parser("doctor", help="Agent health report")
    _agent_options(doctor_p)
    doctor_p.set_defaults(fn=cmd_doctor)

    sub.add_parser("version", help="Print the package version").set_defaults(
        fn=cmd_version)
