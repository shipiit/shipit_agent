"""A sub-agent's work stays one row when other events land in between.

Parallel sub-agents interleave their events. When the parent's own work
settled between two of one child's calls, the child's row was emitted and
its next call started a second row: under load, one child showed as
"Read auth.py" and, separately, "Searched for TODO".
"""

from __future__ import annotations

from typing import Any

from shipit_agent.core.models import AgentEvent
from shipit_agent.narrate import SubAgentRow, build_transcript


def _child(task: str, tool: str, **arguments: Any) -> AgentEvent:
    return AgentEvent(type="sub_agent_event", message="", payload={
        "agent": "sub-agent", "task": task, "inner_type": "tool_called",
        "inner": {"tool": tool, "call_id": f"{task}-{tool}", "arguments": arguments}})


def _parent_text(text: str) -> AgentEvent:
    return AgentEvent(type="text_delta", message="", payload={"chunk": text})


def test_a_childs_calls_stay_in_one_row_across_a_flush() -> None:
    rows = build_transcript([
        _child("Summarize auth", "read_file", path="auth.py"),
        _parent_text("Both reviews are underway. "),
        _child("Summarize auth", "grep_files", pattern="TODO"),
    ])
    sub_rows = [r for r in rows if isinstance(r, SubAgentRow)]
    assert len(sub_rows) == 1
    assert [c.name for c in sub_rows[0].calls] == ["read_file", "grep_files"]


def test_two_children_still_get_a_row_each() -> None:
    rows = build_transcript([
        _child("Summarize auth", "read_file", path="auth.py"),
        _child("Summarize billing", "read_file", path="billing.py"),
        _parent_text("Halfway. "),
        _child("Summarize billing", "grep_files", pattern="TODO"),
        _child("Summarize auth", "grep_files", pattern="TODO"),
    ])
    sub_rows = {r.task: [c.name for c in r.calls] for r in rows if isinstance(r, SubAgentRow)}
    assert sub_rows == {"Summarize auth": ["read_file", "grep_files"],
                        "Summarize billing": ["read_file", "grep_files"]}


def _child_done(task: str) -> AgentEvent:
    return AgentEvent(type="sub_agent_event", message="", payload={
        "agent": "sub-agent", "task": task, "inner_type": "run_completed", "inner": {"output": "done"}})


def _parent(kind: str, **payload: Any) -> AgentEvent:
    return AgentEvent(type=kind, message="", payload=payload)


def test_a_background_child_still_working_when_the_parent_settles_is_shown_whole() -> None:
    import io

    from shipit_agent.narrate.renderer import NarratorRenderer

    events = [
        _parent("tool_called", tool="sub_agent", call_id="p1", arguments={"task": "Summarize auth", "background": True}),
        _parent("tool_completed", tool="sub_agent", call_id="p1", output="started"),
        _child("Summarize auth", "read_file", path="auth.py"),
        _parent("tool_group_completed"),                    # the parent's work settles here...
        _child("Summarize auth", "grep_files", pattern="TODO"),  # ...while the child keeps going
        _child_done("Summarize auth"),
        _parent("run_completed", output="Reviewed."),
    ]
    buffer = io.StringIO()
    renderer = NarratorRenderer(file=buffer, style="plain", show_footer=False)
    for event in events:
        renderer.feed(event)
    renderer.close()
    out = buffer.getvalue()
    assert "Read auth.py, searched for TODO" in out
    assert out.count("sub-agent · Summarize auth") == 1
    rows = build_transcript(events)
    assert [(r.task, [c.name for c in r.calls]) for r in rows if isinstance(r, SubAgentRow)] == [
        ("Summarize auth", ["read_file", "grep_files"])]
