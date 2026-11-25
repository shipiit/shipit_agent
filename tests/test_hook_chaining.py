"""Before-tool hooks run in order, each seeing the arguments as earlier hooks left them."""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.hooks import AgentHooks
from shipit_agent.llms.base import LLMResponse


def _rewrite(path: str) -> Any:
    return lambda name, arguments: {"decision": "allow", "updated_arguments": {**arguments, "path": path}}


def test_a_later_hook_judges_the_rewritten_arguments() -> None:
    hooks = AgentHooks()
    hooks.on_before_tool(_rewrite("/etc/passwd"))
    hooks.on_before_tool(lambda name, arguments: False if arguments["path"].startswith("/etc") else None)
    assert hooks.run_before_tool("write_file", {"path": "notes.txt"}).denied


def test_a_plain_allow_after_a_rewrite_keeps_the_rewrite() -> None:
    hooks = AgentHooks()
    hooks.on_before_tool(_rewrite("safe/notes.txt"))
    hooks.on_before_tool(lambda name, arguments: {"decision": "allow"})
    result = hooks.run_before_tool("write_file", {"path": "notes.txt"})
    assert result.updated_arguments == {"path": "safe/notes.txt"}


def test_rewrites_build_on_each_other() -> None:
    hooks = AgentHooks()
    hooks.on_before_tool(lambda name, a: {"decision": "allow", "updated_arguments": {**a, "path": "a"}})
    hooks.on_before_tool(lambda name, a: {"decision": "allow", "updated_arguments": {**a, "mode": "w"}})
    assert hooks.run_before_tool("write_file", {"path": "x"}).updated_arguments == {"path": "a", "mode": "w"}


def test_an_ask_keeps_the_rewritten_arguments_and_still_asks() -> None:
    hooks = AgentHooks()
    hooks.on_before_tool(_rewrite("b"))
    hooks.on_before_tool(lambda name, arguments: {"decision": "ask", "reason": "review"})
    result = hooks.run_before_tool("write_file", {"path": "a"})
    assert result.needs_approval and result.updated_arguments == {"path": "b"}


def test_observe_only_hooks_still_return_nothing_and_callers_arguments_are_not_changed() -> None:
    seen: list[dict[str, Any]] = []
    hooks = AgentHooks()
    hooks.on_before_tool(lambda name, arguments: seen.append(dict(arguments)))
    original = {"path": "a"}
    assert hooks.run_before_tool("write_file", original) is None and original == {"path": "a"} and seen == [{"path": "a"}]


def test_in_a_run_the_call_uses_the_arguments_every_hook_agreed_to() -> None:
    ran: list[str] = []

    def write(path: str = "") -> str:
        """Write."""
        ran.append(path)
        return "ok"

    class _Model:
        model = "m"
        turn = 0

        def complete(self, **_: Any) -> LLMResponse:
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(tool_calls=[ToolCall(name="write", arguments={"path": "notes.txt"}, id="c1")])
            return LLMResponse(content="done")

    hooks = AgentHooks()
    hooks.on_before_tool(_rewrite("safe/notes.txt"))
    hooks.on_before_tool(lambda name, arguments: {"decision": "allow"})
    Agent(llm=_Model(), tools=[FunctionTool.from_callable(write, name="write")], hooks=hooks).run("go")
    assert ran == ["safe/notes.txt"]
