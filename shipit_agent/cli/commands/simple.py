"""Simple commands: run, doctor, version."""

from __future__ import annotations

import argparse
import json
from typing import Any

from shipit_agent.cli import ui
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
    parser.add_argument("--mcp", default=None,
                        help="comma-separated MCP catalog servers to attach "
                             "(e.g. playwright,filesystem — see `shipit mcp`)")


def cmd_run(args: argparse.Namespace) -> int:
    agent = build_agent(args)
    if args.json:
        result = agent.run(args.prompt)
        print(json.dumps(
            {"output": result.output, "summary": result.summary()}, indent=2))
    else:
        agent.run_live(args.prompt, style=getattr(args, "style", "modern"))
    return 0


#: Marker and palette tone per check status.
_STATUS = {
    "pass": ("✓", "ok"),
    "warn": ("!", "warn"),
    "fail": ("✗", "err"),
}


def cmd_doctor(args: argparse.Namespace) -> int:
    """Render the health report.

    This printed the dataclass — one 2,000-character line of
    `DoctorReport(checks=[DoctorCheck(name=…` that you had to read like a
    stack trace. The point of a health check is to be scanned, so failures
    and warnings come first and carry their details; passing checks are one
    line each, because their details are only interesting when something
    is wrong.
    """
    agent = build_agent(args)
    report = agent.doctor()

    # Both branches report the same verdict: a script that pipes --json
    # to jq must not see success where the terminal shows a failure.
    code = 0 if report.passed else 1

    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return code

    ui.out()
    ui.out(ui.style("Agent health", "title"))
    ui.rule()

    ordered = report.failures + report.warnings + [
        check for check in report.checks if check.status == "pass"
    ]
    for check in ordered:
        mark, tone = _STATUS.get(check.status, ("·", "dim"))
        ui.out(f"  {ui.style(mark, tone)} {ui.style(check.name, 'bold'):<26} "
               f"{check.message}")
        if check.status != "pass":
            for key, value in check.details.items():
                ui.out(f"      {ui.style(f'{key}:', 'dim')} {value}")

    ui.rule()
    counts = (f"{len(report.checks)} checks · {len(report.failures)} failed · "
              f"{len(report.warnings)} warnings")
    ui.out("  " + ui.style(counts, "ok" if report.passed else "err"))
    ui.out()

    # A failing check is a failing command — `shipit doctor && deploy`
    # should not proceed past a broken agent.
    return code


def cmd_version(_args: argparse.Namespace) -> int:
    import shipit_agent

    print(getattr(shipit_agent, "__version__", "unknown"))
    return 0


def register(sub: Any) -> None:
    run_p = sub.add_parser("run", help="One-shot prompt with live tool cards")
    run_p.add_argument("prompt")
    run_p.add_argument("--style", choices=["modern", "rich", "plain"],
                       default="modern",
                       help="transcript style (default: modern)")
    run_p.add_argument("--json", action="store_true",
                       help="print result + metrics as JSON")
    _agent_options(run_p)
    run_p.set_defaults(fn=cmd_run)

    doctor_p = sub.add_parser("doctor", help="Agent health report")
    doctor_p.add_argument("--json", action="store_true",
                          help="print the full report as JSON")
    _agent_options(doctor_p)
    doctor_p.set_defaults(fn=cmd_doctor)

    sub.add_parser("version", help="Print the package version").set_defaults(
        fn=cmd_version)
