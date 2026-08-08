from __future__ import annotations

from shipit_agent import Agent, AgentTool
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.models import ToolCall
from shipit_agent.stores import InMemorySessionStore
from shipit_agent.tools.base import ToolContext


class DelegateOnceLLM:
    def __init__(self) -> None:
        self.called = False

    def complete(self, **_kwargs):
        if not self.called:
            self.called = True
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="researcher",
                        arguments={
                            "task": "Investigate the cache",
                            "details": "Focus on invalidation.",
                        },
                    )
                ]
            )
        return LLMResponse(content="Delegation complete")


def test_agent_as_tool_delegates_and_surfaces_nested_events() -> None:
    child = Agent(
        llm=SimpleEchoLLM(),
        name="researcher",
        description="Investigates technical questions.",
        auto_use_skills=False,
    )
    tool = child.as_tool()
    parent = Agent(
        llm=DelegateOnceLLM(),
        tools=[tool],
        auto_use_skills=False,
    )

    result = parent.run("Delegate this investigation")

    assert isinstance(tool, AgentTool)
    assert result.output == "Delegation complete"
    assert result.tool_results[0].metadata["delegated"] is True
    assert "Focus on invalidation" in result.tool_results[0].output
    assert any(event.type == "sub_agent_event" for event in result.events)


def test_agent_tool_can_reuse_a_durable_child_session() -> None:
    store = InMemorySessionStore()
    child = Agent(
        llm=SimpleEchoLLM(),
        name="writer",
        session_store=store,
        auto_use_skills=False,
    )
    tool = child.as_tool(session_id="shared-child", stream_events=False)
    context = ToolContext(prompt="", state={})

    first = tool.run(context, task="Draft section one")
    second = tool.run(context, task="Continue with section two")

    assert first.metadata["session_id"] == "shared-child"
    assert second.metadata["session_id"] == "shared-child"
    record = store.load("shared-child")
    assert record is not None
    assert len([message for message in record.messages if message.role == "user"]) == 2


def test_agent_tool_reports_missing_task_without_running_child() -> None:
    tool = Agent(llm=SimpleEchoLLM(), auto_use_skills=False).as_tool(name="helper")
    output = tool.run(ToolContext(prompt="", state={}))
    assert output.metadata == {
        "ok": False,
        "error": "missing_argument",
        "argument": "task",
    }


class _Exploding:
    def stream(self, prompt):
        raise RuntimeError("the provider is down")

    def run(self, prompt):
        raise RuntimeError("the provider is down")


class _Silent:
    def run(self, prompt):
        return type("R", (), {"output": "", "events": []})()


def test_a_child_that_fails_does_not_end_the_parents_turn() -> None:
    """Every other tool reports failure as a result the model can act on.
    A raising child would take the whole turn down with it, when the
    parent could have said so, tried something else, or answered without
    it."""
    from shipit_agent.tools.agent_tool import AgentTool
    from shipit_agent.tools.base import ToolContext

    tool = AgentTool(agent=_Exploding(), name="researcher", description="d")
    out = tool.run(ToolContext(prompt="", state={}), task="find the thing")

    assert out.metadata["ok"] is False
    assert out.metadata["error"] == "child_failed"
    assert "provider is down" in out.text


def test_delegation_cannot_recurse_forever() -> None:
    """An agent holding a tool that wraps an agent holding the same tool
    recurses until something runs out. `sub_agent` caps this, and an
    AgentTool is the same hazard by another name — so it shares the
    counter rather than keeping its own."""
    from shipit_agent.tools.agent_tool import AgentTool
    from shipit_agent.tools.base import ToolContext
    from shipit_agent.tools.sub_agent.sub_agent_tool import (
        DEPTH_STATE_KEY,
        MAX_DEPTH,
    )

    tool = AgentTool(agent=_Exploding(), name="researcher", description="d")
    out = tool.run(
        ToolContext(prompt="", state={DEPTH_STATE_KEY: MAX_DEPTH}),
        task="find the thing")

    assert out.metadata["error"] == "max_depth"
    assert "yourself" in out.text, "a cap that does not say what to do "\
                                   "instead just gets retried"


def test_a_child_that_returns_nothing_is_not_reported_as_success() -> None:
    from shipit_agent.tools.agent_tool import AgentTool
    from shipit_agent.tools.base import ToolContext

    tool = AgentTool(agent=_Silent(), name="researcher", description="d",
                     stream_events=False)
    out = tool.run(ToolContext(prompt="", state={}), task="find the thing")

    assert out.metadata["ok"] is False
    assert "returned nothing" in out.text
