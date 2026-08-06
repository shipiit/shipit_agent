"""sub_agent — a real delegated agent loop, not one completion."""

from __future__ import annotations


from shipit_agent import SubAgentTool
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolContext, ToolOutput
from shipit_agent.tools.sub_agent.sub_agent_tool import (
    DEPTH_STATE_KEY,
    MAX_DEPTH,
    PARENT_STATE_KEY,
)


def recording_tool(name: str, calls: list, output: str = "tool output"):
    class T:
        def __init__(self):
            self.name = name
            self.description = name
            self.prompt_instructions = ""

        def schema(self):
            return {"function": {"name": name, "parameters": {
                "properties": {"path": {"type": "string"}}}}}

        def run(self, context, **kwargs):
            calls.append((name, kwargs))
            return ToolOutput(text=output)

    return T()


class ScriptedLLM:
    model = "test-model"

    def __init__(self, script):
        self.script = list(script)
        self.n = 0
        self.seen_tools: list[list[str]] = []

    def complete(self, *, messages, tools=None, system_prompt=None,
                 metadata=None, text_delta_callback=None):
        self.seen_tools.append(
            [(t.get("function") or {}).get("name") for t in (tools or [])]
        )
        step = self.script[self.n] if self.n < len(self.script) else ("done", [])
        self.n += 1
        return LLMResponse(
            content=step[0],
            tool_calls=[ToolCall(name=n, arguments=a) for n, a in step[1]],
        )


def parent_context(tools=None, depth=0, **control):
    return ToolContext(
        prompt="parent task",
        metadata={DEPTH_STATE_KEY: depth},
        state={
            PARENT_STATE_KEY: {"tools": tools or [], "project_root": ".", **control},
            DEPTH_STATE_KEY: depth,
        },
    )


class TestItActuallyRuns:
    def test_the_sub_agent_uses_tools(self) -> None:
        """The old implementation could not do this at all."""
        calls: list = []
        tool = SubAgentTool(llm=ScriptedLLM([
            ("", [("read_file", {"path": "a.py"})]),
            ("It defines login().", []),
        ]))
        out = tool.run(
            parent_context(tools=[recording_tool("read_file", calls)]),
            task="What does a.py do?",
        )
        assert calls == [("read_file", {"path": "a.py"})]
        assert out.text == "It defines login()."
        assert out.metadata["tool_call_count"] == 1

    def test_it_reports_iterations_and_usage(self) -> None:
        calls: list = []
        out = SubAgentTool(llm=ScriptedLLM([
            ("", [("read_file", {"path": "a"})]),
            ("", [("read_file", {"path": "b"})]),
            ("Both read.", []),
        ])).run(
            parent_context(tools=[recording_tool("read_file", calls)]),
            task="read both",
        )
        assert out.metadata["tool_call_count"] == 2
        assert out.metadata["iterations"] >= 2
        assert out.metadata["ok"] is True

    def test_supporting_details_reach_the_child(self) -> None:
        seen: list = []

        class Capturing(ScriptedLLM):
            def complete(self, *, messages, **kw):
                seen.extend(m.content for m in messages if m.role == "user")
                return super().complete(messages=messages, **kw)

        SubAgentTool(llm=Capturing([("ok", [])])).run(
            parent_context(), task="Summarize", details="The file is at src/a.py"
        )
        assert any("src/a.py" in text for text in seen)

    def test_a_missing_task_is_refused(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([])).run(parent_context())
        assert out.metadata["ok"] is False

    def test_a_crashing_child_is_reported_not_raised(self) -> None:
        class Exploding:
            model = "m"

            def complete(self, **_):
                raise RuntimeError("provider down")

        out = SubAgentTool(llm=Exploding()).run(parent_context(), task="go")
        assert out.metadata["ok"] is False
        assert "provider down" in out.text

    def test_a_child_that_gives_up_says_why(self) -> None:
        from shipit_agent.tools.give_up import GiveUpTool

        out = SubAgentTool(llm=ScriptedLLM([
            ("", [("give_up", {"reason": "no credentials"})]),
            ("blocked", []),
        ])).run(parent_context(tools=[GiveUpTool()]), task="deploy")
        assert out.metadata["gave_up"] is True
        assert "no credentials" in out.text


class TestInheritance:
    """A sub-agent can never do more than its parent."""

    def test_it_inherits_the_parents_tools(self) -> None:
        calls: list = []
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        tool.run(
            parent_context(tools=[
                recording_tool("read_file", calls),
                recording_tool("bash", calls),
            ]),
            task="go",
        )
        assert set(tool.llm.seen_tools[0]) == {"read_file", "bash"}

    def test_it_cannot_see_itself(self) -> None:
        # Belt and braces alongside the depth cap.
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        tool.run(parent_context(tools=[tool, recording_tool("read_file", [])]),
                 task="go")
        assert "sub_agent" not in tool.llm.seen_tools[0]

    def test_it_never_gets_the_human_prompt_tools(self) -> None:
        # The parent is mid-turn; nobody is watching the child's stdout.
        from shipit_agent.tools.ask_user import AskUserTool

        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        tool.run(
            parent_context(tools=[AskUserTool(), recording_tool("read_file", [])]),
            task="go",
        )
        assert "ask_user" not in tool.llm.seen_tools[0]

    def test_it_inherits_the_permission_engine(self) -> None:
        """Delegation must not be a way around the parent's policy."""
        from shipit_agent.permissions import PermissionEngine

        calls: list = []
        out = SubAgentTool(llm=ScriptedLLM([
            ("", [("bash", {"command": "rm -rf /"})]),
            ("stopped", []),
        ])).run(
            parent_context(
                tools=[recording_tool("bash", calls)],
                permissions=PermissionEngine(deny=["bash"]),
            ),
            task="clean up",
        )
        assert calls == []  # denied in the child, by the parent's rule
        assert out.metadata["ok"] is True

    def test_it_inherits_the_approval_queue(self) -> None:
        from shipit_agent import ApprovalQueue
        from shipit_agent.permissions import PermissionEngine

        calls: list = []
        queue = ApprovalQueue()
        SubAgentTool(llm=ScriptedLLM([
            ("", [("slack", {"channel": "#eng"})]),
            ("queued", []),
        ])).run(
            parent_context(
                tools=[recording_tool("slack", calls)],
                approvals=queue,
                permissions=PermissionEngine(ask=["slack"]),
            ),
            task="tell the team",
        )
        assert calls == []
        # The parent's queue holds it — one review pass, not two.
        assert len(queue.pending()) == 1

    def test_an_explicit_toolset_overrides_inheritance(self) -> None:
        calls: list = []
        narrow = recording_tool("only_this", calls)
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]), tools=[narrow])
        tool.run(parent_context(tools=[recording_tool("bash", calls)]), task="go")
        assert tool.llm.seen_tools[0] == ["only_this"]


class TestDepth:
    def test_delegation_is_capped(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(depth=MAX_DEPTH), task="delegate again"
        )
        assert out.metadata["error"] == "max_depth"
        assert "yourself" in out.text

    def test_below_the_cap_it_proceeds(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(depth=MAX_DEPTH - 1), task="go"
        )
        assert out.metadata.get("error") != "max_depth"

    def test_the_child_knows_its_depth(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        agent = tool._build_agent(parent_context(depth=0), "", 0)
        assert agent.metadata[DEPTH_STATE_KEY] == 1


class TestAgentTypes:
    def test_a_known_role_is_used(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        agent = tool._build_agent(parent_context(), "researcher", 0)
        assert agent.name == "researcher"

    def test_an_unknown_role_falls_back_rather_than_failing(self) -> None:
        # An unknown role is the model guessing; losing the delegation over it
        # would be worse than running general-purpose.
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        out = tool.run(parent_context(), task="go", agent_type="wizard")
        assert out.metadata["ok"] is True

    def test_the_role_is_reported(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(), task="go", agent_type="researcher"
        )
        assert out.metadata["agent_type"] == "researcher"


class TestBackground:
    def test_it_returns_a_task_id_immediately(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(), task="slow thing", background=True
        )
        assert out.metadata["background"] is True
        assert out.metadata["task_id"].startswith("task-")

    def test_collect_returns_the_result(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("the answer", [])]))
        started = tool.run(parent_context(), task="go", background=True)
        collected = tool.run(parent_context(), collect=started.metadata["task_id"])
        assert collected.text == "the answer"

    def test_collect_all_gathers_everything(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("a", []), ("b", []), ("c", [])]))
        for i in range(3):
            tool.run(parent_context(), task=f"task {i}", background=True)
        out = tool.run(parent_context(), collect="all")
        assert out.metadata["collected"] == 3
        assert tool.outstanding() == []

    def test_collect_all_with_nothing_outstanding(self) -> None:
        out = SubAgentTool(llm=ScriptedLLM([])).run(parent_context(), collect="all")
        assert out.metadata["collected"] == 0

    def test_an_unknown_id_lists_what_exists(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("a", [])]))
        tool.run(parent_context(), task="go", background=True)
        out = tool.run(parent_context(), collect="task-99")
        assert out.metadata["ok"] is False
        assert "task-1" in out.text

    def test_a_task_is_dropped_after_collection(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("a", [])]))
        task_id = tool.run(parent_context(), task="go",
                           background=True).metadata["task_id"]
        tool.run(parent_context(), collect=task_id)
        assert tool.run(parent_context(), collect=task_id).metadata["ok"] is False

    def test_outstanding_reports_running_work(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("a", [])]))
        tool.run(parent_context(), task="the task", background=True,
                 agent_type="researcher")
        outstanding = tool.outstanding()
        assert outstanding[0]["task"] == "the task"
        assert outstanding[0]["agent_type"] == "researcher"


class TestArgumentNaming:
    def test_the_details_argument_is_not_called_context(self) -> None:
        """`context` would be silently stripped before the tool saw it.

        ToolRunner removes `context` and `self` from tool arguments because
        they collide with the positional ToolContext. The original tool named
        this parameter `context`, so supporting context never arrived.
        """
        from shipit_agent.tool_runner import ToolRunner

        params = SubAgentTool(llm=ScriptedLLM([]))\
            .schema()["function"]["parameters"]["properties"]
        assert "details" in params
        assert not set(params) & ToolRunner._RESERVED_ARG_NAMES

    def test_details_survive_the_tool_runner(self) -> None:
        from shipit_agent.registry import ToolRegistry
        from shipit_agent.tool_runner import ToolRunner
        from shipit_agent.models import ToolCall

        seen: list = []

        class Capturing(ScriptedLLM):
            def complete(self, *, messages, **kw):
                seen.extend(m.content for m in messages if m.role == "user")
                return super().complete(messages=messages, **kw)

        tool = SubAgentTool(llm=Capturing([("ok", [])]))
        runner = ToolRunner(ToolRegistry.build(tools=[tool]))
        runner.run_tool_call(
            ToolCall(name="sub_agent",
                     arguments={"task": "Summarize", "details": "path is src/a.py"}),
            parent_context(),
        )
        assert any("src/a.py" in text for text in seen)


class TestCompatibility:
    def test_a_duck_typed_context_still_works(self) -> None:
        # Embedders and older tests pass lighter stand-ins than ToolContext.
        out = SubAgentTool(llm=ScriptedLLM([("ok", [])])).run(
            type("Ctx", (), {"prompt": "parent"})(), task="Summarize this"
        )
        assert out.metadata["delegated"] is True


class TestMetadataKeyCollisions:
    """A tool result's metadata is merged onto its message — mind the keys."""

    def test_the_call_count_is_not_under_the_reserved_key(self) -> None:
        """`tool_calls` on message metadata means the assistant's records.

        Putting an int there made the LiteLLM serializer iterate an integer,
        which only surfaced when a sub-agent result flowed back into a real
        conversation. Found live against Gemma on Bedrock.
        """
        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(), task="go"
        )
        assert "tool_calls" not in out.metadata
        assert isinstance(out.metadata["tool_call_count"], int)

    def test_a_sub_agent_result_serializes_for_litellm(self) -> None:
        from shipit_agent.llms.litellm_adapter import _serialize_message
        from shipit_agent.models import Message

        out = SubAgentTool(llm=ScriptedLLM([("done", [])])).run(
            parent_context(), task="go"
        )
        message = Message(
            role="tool", name="sub_agent", content=out.text,
            metadata={**out.metadata, "tool_call_id": "call_1_1"},
        )
        payload = _serialize_message(message)
        assert payload["role"] == "tool"

    def test_a_non_list_under_the_key_is_ignored_not_fatal(self) -> None:
        # Any tool can land a value there; it must never break the request.
        from shipit_agent.llms.litellm_adapter import _serialize_message
        from shipit_agent.models import Message

        for value in (3, "x", {"a": 1}, None):
            payload = _serialize_message(
                Message(role="tool", content="x", metadata={"tool_calls": value})
            )
            assert "tool_calls" not in payload


class TestSchemaIsUnambiguous:
    """An all-optional schema invites a weaker model to send `{}`.

    Observed live against Gemma 4 on Bedrock: the tool was called with no
    arguments at all, and the run spent 47 seconds arriving at "provide
    `task`". A schema that marks nothing required says nothing is needed.
    """

    def test_task_is_required(self) -> None:
        schema = SubAgentTool(llm=ScriptedLLM([])).schema()
        assert schema["function"]["parameters"]["required"] == ["task"]

    def test_collect_still_works_with_a_task_present(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("answer", [])]))
        task_id = tool.run(parent_context(), task="go",
                           background=True).metadata["task_id"]
        # A collect call repeats the task text; collect wins.
        out = tool.run(parent_context(), task="go", collect=task_id)
        assert out.text == "answer"

    def test_no_builtin_has_parameters_but_nothing_required(self) -> None:
        """Unless it handles an empty call sensibly, which the exceptions do."""
        from shipit_agent.builtins import get_builtin_tools

        handles_empty = {"connections"}  # defaults to action="list"
        for tool in get_builtin_tools(llm=None, project_root="."):
            parameters = tool.schema()["function"]["parameters"]
            properties = list((parameters.get("properties") or {}))
            required = list(parameters.get("required") or [])
            if properties and not required:
                assert getattr(tool, "name", "") in handles_empty, (
                    f"{tool.name} marks nothing required and is not known to "
                    f"handle an empty call"
                )


class TestBackgroundIsNotLater:
    """The failure this guards: the model starts background tasks, tells the
    user it will "present the consolidated results", and answers. The turn
    ends, the futures are discarded, and the user waits for a message that
    is never coming."""

    def test_starting_one_says_it_must_be_collected_first(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        out = tool.run(parent_context(), task="summarize the file",
                       background=True)
        assert "before you answer" in out.text.lower()
        assert "no later" in out.text.lower(), (
            "the model has to be told the turn ends with its answer, or it "
            "writes a promise it cannot keep")

    def test_the_description_says_the_same(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([]))
        assert "same turn" in tool.prompt_instructions.lower()


class TestThinDelegations:
    """A model that delegates reflexively sends a task with nothing in it.

    Observed on Gemma 4: `sub_agent(task=",")`, which the tool accepted,
    burning a model call to return an error. The tool has to be hard to
    misuse, because the instruction not to misuse it is only advice.
    """

    def test_a_task_with_no_substance_is_refused(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        out = tool.run(parent_context(), task=",")
        assert out.metadata["ok"] is False
        assert "nothing to delegate" in out.text.lower()

    def test_the_refusal_says_what_to_do_instead(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        out = tool.run(parent_context(), task="...")
        assert "do it yourself" in out.text.lower(), (
            "a refusal that does not name the alternative just gets retried")

    def test_a_short_but_real_task_is_not_refused(self) -> None:
        """The guard is about substance, not length — plenty of honest
        briefs are three words."""
        tool = SubAgentTool(llm=ScriptedLLM([("done", [])]))
        out = tool.run(parent_context(), task="summarize the log")
        assert out.metadata.get("ok") is not False

    def test_a_real_brief_still_goes_through(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([("found it", [])]))
        out = tool.run(parent_context(),
                       task="Read inbox/msg-1.eml and return the sender name")
        assert out.metadata.get("ok") is not False

    def test_the_description_says_when_not_to_delegate(self) -> None:
        tool = SubAgentTool(llm=ScriptedLLM([]))
        assert "do not delegate" in tool.prompt_instructions.lower()
