"""Sub-agent start and stop hooks, like the Claude Agent SDK's.

A start hook sees each delegation before the child exists: it can refuse it,
or add context to the child's brief. A stop hook sees how each one ended.
"""

from __future__ import annotations

import tempfile
from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.hooks import AgentHooks


def _read(path: str = "") -> str:
    """Read something."""
    return f"read {path}"


class _Delegates:
    """Parent delegates once, then answers; the child echoes its brief."""

    def __init__(self) -> None:
        self.child_briefs: list[str] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "You review code" in system:
            brief = next(m.content for m in messages if m.role == "user")
            self.child_briefs.append(str(brief))
            return LLMResponse(content="Reviewed.")
        if any(m.role == "tool" for m in messages):
            tool_text = next(m.content for m in messages if m.role == "tool")
            return LLMResponse(content=f"Parent saw: {tool_text}")
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    name="sub_agent",
                    arguments={"task": "Review app.py", "agent_type": "reviewer"},
                )
            ],
        )


def _agent(llm: Any, hooks: AgentHooks) -> Agent:
    return Agent(
        llm=llm,
        tools=[FunctionTool.from_callable(_read, name="read_file")],
        agents={
            "reviewer": {
                "description": "Use for code review.",
                "prompt": "You review code.",
            }
        },
        hooks=hooks,
        project_root=tempfile.mkdtemp(),
    )


def test_the_start_hook_sees_the_delegation_and_can_add_context() -> None:
    seen: list[tuple[str, str]] = []
    hooks = AgentHooks()

    @hooks.on_subagent_start
    def start(agent_type: str, task: str) -> str:
        seen.append((agent_type, task))
        return "The repo uses tabs."

    llm = _Delegates()
    _agent(llm, hooks).run("get a review")
    assert seen == [("reviewer", "Review app.py")]
    assert "The repo uses tabs." in llm.child_briefs[0]


def test_the_start_hook_can_refuse_a_delegation() -> None:
    hooks = AgentHooks()
    hooks.on_subagent_start(lambda agent_type, task: False)
    llm = _Delegates()
    result = _agent(llm, hooks).run("get a review")
    assert llm.child_briefs == []
    assert "refused" in result.output


def test_the_stop_hook_sees_how_it_ended() -> None:
    ended: list[dict[str, Any]] = []
    hooks = AgentHooks()
    hooks.on_subagent_stop(
        lambda agent_type, task, output, error: ended.append(
            {"agent_type": agent_type, "task": task, "output": output, "error": error}
        )
    )
    _agent(_Delegates(), hooks).run("get a review")
    assert ended == [
        {
            "agent_type": "reviewer",
            "task": "Review app.py",
            "output": "Reviewed.",
            "error": "",
        }
    ]


def test_without_hooks_delegation_is_unchanged() -> None:
    llm = _Delegates()
    _agent(llm, AgentHooks()).run("get a review")
    # The runtime may append its own standing reminder; nothing else is added.
    assert len(llm.child_briefs) == 1
    assert llm.child_briefs[0].startswith("Review app.py")
    assert "Context:" not in llm.child_briefs[0]
