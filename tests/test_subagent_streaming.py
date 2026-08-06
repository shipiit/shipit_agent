"""A delegated agent's work is visible in the parent's transcript."""

from __future__ import annotations

import io
import time

from shipit_agent import Agent, SubAgentTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import AgentEvent, ToolCall
from shipit_agent.narrate.grouping import SubAgentRow, WorkRow, build_transcript
from shipit_agent.narrate.renderer import NarratorRenderer
from shipit_agent.tools.base import ToolOutput


def tool(name, output="ok", delay=0.0, log=None):
    class T:
        def __init__(self):
            self.name = name
            self.description = name
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {"properties": {
                "path": {"type": "string"}, "pattern": {"type": "string"}}}}}

        def run(self, context, **kwargs):
            if delay:
                time.sleep(delay)
            if log is not None:
                log.append((time.monotonic(), name))
            return ToolOutput(text=output)

    return T()


class ChildLLM:
    """Reads a file, greps, then reports — per distinct brief."""

    model = "m"

    def __init__(self):
        self.turns: dict[str, int] = {}

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        brief = " ".join(m.content for m in messages if m.role == "user")
        key = "auth" if "auth" in brief else "billing"
        self.turns[key] = self.turns.get(key, 0) + 1
        turn = self.turns[key]
        if turn == 1:
            return LLMResponse(tool_calls=[
                ToolCall(name="read_file", arguments={"path": f"{key}.py"})])
        if turn == 2:
            return LLMResponse(tool_calls=[
                ToolCall(name="grep_files", arguments={"pattern": "TODO"})])
        return LLMResponse(content=f"{key} reviewed", usage={"total_tokens": 100})


class ParentLLM:
    model = "m"

    def __init__(self, script):
        self.script = list(script)
        self.n = 0

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        step = self.script[self.n] if self.n < len(self.script) else ("", [])
        self.n += 1
        if step[0] and text_delta_callback:
            text_delta_callback(step[0])
        return LLMResponse(
            content=step[0],
            tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
            usage={"total_tokens": 200},
        )


PARALLEL_SCRIPT = [
    ("I'll review both in parallel.",
     [("sub_agent", {"task": "Summarize the auth module", "background": True}),
      ("sub_agent", {"task": "Summarize the billing module", "background": True})]),
    ("", [("sub_agent", {"collect": "all"})]),
    ("Both reviewed.", []),
]


def build(script=PARALLEL_SCRIPT, log=None, child=None):
    return Agent(
        llm=ParentLLM(script),
        tools=[
            SubAgentTool(llm=child or ChildLLM()),
            tool("read_file", "def login(): ...", log=log),
            tool("grep_files", "2 matches", log=log),
        ],
        auto_use_skills=False,
        max_iterations=6,
    )


class TestItReallyRuns:
    def test_children_execute_real_tools(self) -> None:
        log: list = []
        build(log=log).run("review both")
        assert sorted(n for _, n in log) == [
            "grep_files", "grep_files", "read_file", "read_file"
        ]

    def test_background_children_overlap(self) -> None:
        """Delegation is only worth it if the work actually runs at once."""
        log: list = []
        Agent(
            llm=ParentLLM(PARALLEL_SCRIPT),
            tools=[
                SubAgentTool(llm=ChildLLM()),
                tool("read_file", "x", delay=0.12, log=log),
                tool("grep_files", "y", delay=0.12, log=log),
            ],
            auto_use_skills=False, max_iterations=6,
        ).run("review both")
        times = sorted(t for t, _ in log)
        # Four 0.12s calls run serially would span ~0.48s.
        assert times[-1] - times[0] < 0.35, "children ran serially"


class TestEventsReachTheParent:
    def test_child_work_is_emitted_on_the_parent_stream(self) -> None:
        result = build().run("review both")
        events = [e for e in result.events if e.type == "sub_agent_event"]
        assert events, "the child's work never reached the parent"

    def test_events_say_which_child_produced_them(self) -> None:
        result = build().run("review both")
        tasks = {
            e.payload["task"] for e in result.events
            if e.type == "sub_agent_event"
        }
        assert tasks == {"Summarize the auth module", "Summarize the billing module"}

    def test_child_events_keep_their_own_type_nested(self) -> None:
        """A nested read_file must not look like the parent read a file."""
        result = build().run("review both")
        parent_reads = [
            e for e in result.events
            if e.type == "tool_called" and e.payload.get("tool") == "read_file"
        ]
        assert parent_reads == []
        nested = [
            e for e in result.events
            if e.type == "sub_agent_event" and e.payload["inner_type"] == "tool_called"
        ]
        assert len(nested) == 4

    def test_a_raising_sink_does_not_break_delegation(self) -> None:
        from shipit_agent.tools.sub_agent.sub_agent_tool import EVENT_SINK_KEY
        from shipit_agent.tools.base import ToolContext

        def boom(*_args):
            raise RuntimeError("renderer exploded")

        sub = SubAgentTool(llm=ChildLLM())
        out = sub.run(
            ToolContext(prompt="p", metadata={}, state={
                EVENT_SINK_KEY: boom,
                "subagent_parent": {"tools": [tool("read_file")], "project_root": "."},
            }),
            task="Summarize the auth module",
        )
        assert out.metadata["ok"] is True

    def test_without_a_sink_it_still_works(self) -> None:
        from shipit_agent.tools.base import ToolContext

        out = SubAgentTool(llm=ChildLLM()).run(
            ToolContext(prompt="p", metadata={}, state={
                "subagent_parent": {"tools": [tool("read_file")], "project_root": "."},
            }),
            task="Summarize the auth module",
        )
        assert out.metadata["ok"] is True


class TestRendering:
    def test_child_work_becomes_its_own_row(self) -> None:
        rows = build_transcript(build().run("review both").events)
        sub_rows = [r for r in rows if isinstance(r, SubAgentRow)]
        assert len(sub_rows) == 2

    def test_the_row_is_labelled_by_the_same_rules_as_the_parents(self) -> None:
        rows = build_transcript(build().run("review both").events)
        labels = {r.label for r in rows if isinstance(r, SubAgentRow)}
        assert labels == {
            "Read auth.py, searched for TODO",
            "Read billing.py, searched for TODO",
        }

    def test_the_row_names_its_task(self) -> None:
        rows = build_transcript(build().run("review both").events)
        tasks = {r.task for r in rows if isinstance(r, SubAgentRow)}
        assert "Summarize the auth module" in tasks

    def test_children_sit_under_the_delegation_that_started_them(self) -> None:
        rows = build_transcript(build().run("review both").events)
        kinds = [type(r).__name__ for r in rows]
        assert kinds.index("WorkRow") < kinds.index("SubAgentRow")

    def test_it_renders_indented(self) -> None:
        buffer = io.StringIO()
        renderer = NarratorRenderer(file=buffer, style="plain", show_footer=False)
        for event in build().run("review both").events:
            renderer.feed(event)
        renderer.close()
        output = buffer.getvalue()
        assert "Read auth.py, searched for TODO" in output
        assert "Summarize the auth module" in output
        # Nested deeper than the parent's own rows.
        nested = [line for line in output.splitlines() if "searched for TODO" in line][0]
        parent = [line for line in output.splitlines()
                  if "Delegated 2 tasks" in line][0]
        assert len(nested) - len(nested.lstrip()) > len(parent) - len(parent.lstrip())

    def test_a_childs_prose_is_not_repeated(self) -> None:
        # The parent already reports the conclusion; showing both says
        # everything twice.
        rows = build_transcript([
            AgentEvent(type="sub_agent_event", message="", payload={
                "agent": "researcher", "task": "t", "inner_type": "text_delta",
                "inner": {"chunk": "child reasoning"}}),
            AgentEvent(type="run_completed", message="", payload={"output": ""}),
        ])
        assert not any("child reasoning" in getattr(r, "text", "") for r in rows)


class TestLabelShapes:
    def test_starting_and_collecting_are_counted_separately(self) -> None:
        """Two delegations and a collection are never "Delegated 3 tasks".

        They now land in two rows rather than one composite label, because
        the runtime declares a tool group per iteration and the starts and
        the collection happened in different turns. Same distinction, drawn
        where the run actually drew it.
        """
        rows = build_transcript(build().run("review both").events)
        labels = [r.group.label for r in rows if isinstance(r, WorkRow)]
        assert labels[0] == "Delegated 2 tasks"
        assert any("ollect" in label for label in labels[1:]), labels
