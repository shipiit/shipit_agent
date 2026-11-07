"""The timeline as a Markdown report, for a PR comment or a run log."""

from __future__ import annotations

import json
from typing import Any, Iterable

from shipit_agent.core.models import AgentEvent

from .builder import timeline


def render_markdown(
    source: Iterable[AgentEvent] | Any,
    *,
    goal: str | None = None,
    title: str = "Agent Run",
    output_limit: int = 1200,
) -> str:
    """The same timeline as a readable report.

    Sections are numbered as they happened — tool groups, decisions, and the
    final answer — with each call's input and result as JSON blocks. Good for
    a PR comment, a run log, or a notebook cell.
    """
    steps = timeline(source)
    lines: list[str] = [f"## {title}", ""]

    goal = goal or next(
        (s.get("goal") for s in steps if s["type"] == "run_started"), None
    )
    if goal:
        lines += [f"**Goal:** {goal}", "", "---", ""]

    section = 0
    calls: dict[str, dict[str, Any]] = {}
    total_ms = 0.0

    for step in steps:
        kind = step["type"]
        if kind == "reasoning_summary":
            section += 1
            lines += [
                f"### {section}. Understanding the request",
                "",
                str(step["content"]),
                "",
                "**Status:** Completed",
                "",
                "---",
                "",
            ]
        elif kind == "tool_group_started":
            section += 1
            lines += [f"### {section}. Tool calls", "", f"#### {step['title']}", ""]
        elif kind == "tool_call_started":
            calls[str(step["tool_call_id"])] = step
            lines += [f"##### `{step['tool_name']}`", ""]
            if step["input"]:
                lines += ["**Input**", "", "```json", _dump(step["input"]), "```", ""]
        elif kind == "tool_call_completed":
            total_ms += float(step.get("duration_ms") or 0)
            lines += [
                f"**Status:** {str(step['status']).capitalize()}  ",
                f"**Duration:** {step.get('duration_ms', 0):.0f} ms",
                "",
            ]
            body = step.get("output", step.get("error", ""))
            if body not in ("", None):
                lines += [
                    "**Result**",
                    "",
                    "```json",
                    _dump(body)[:output_limit],
                    "```",
                    "",
                ]
        elif kind == "tool_group_completed":
            lines += ["---", ""]
        elif kind == "artifact_created":
            lines += [f"📎 **{step['title']}** — {step['kind']} · `{step['path']}`", ""]
        elif kind == "agent_observation":
            section += 1
            lines += [
                f"### {section}. Observation",
                "",
                str(step["content"]),
                "",
                "---",
                "",
            ]
        elif kind == "agent_decision":
            section += 1
            lines += [
                f"### {section}. Agent decision",
                "",
                str(step["content"]),
                "",
                f"**Next action:** {step['next_action']}",
                "",
                "---",
                "",
            ]
        elif kind == "approval_required":
            section += 1
            lines += [
                f"### {section}. Approval required",
                "",
                f"{step['title']} — `{step.get('tag') or step['tool_name']}`",
                "",
                "---",
                "",
            ]
        elif kind == "connection_required":
            section += 1
            lines += [
                f"### {section}. Connection required",
                "",
                f"**{step['title']}** — {step['reason']}",
                "",
                f"`{step['connection_id']}` · {step['auth']}",
                "",
                "---",
                "",
            ]
        elif kind == "sub_agent_tool_call":
            lines += [
                f"- **{step['agent']}** ran `{step['tool_name']}` "
                f"— {step['task'][:80]}",
                "",
            ]
        elif kind == "notice":
            lines += [f"> {step['content']}", ""]
        elif kind == "final_response":
            section += 1
            lines += [
                f"### {section}. Final response",
                "",
                str(step["content"]),
                "",
                "**Run status:** Successful  ",
                f"**Tool calls:** {step['tool_calls']}  ",
                f"**Total tool duration:** {total_ms / 1000:.2f} seconds",
                "",
            ]
            usage = step.get("usage") or {}
            tokens = int(usage.get("total_tokens") or 0)
            if tokens:
                lines.append(f"**Tokens:** {tokens:,}")
    return "\n".join(lines).rstrip() + "\n"


def _dump(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - default= covers it
        return str(value)
