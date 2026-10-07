import asyncio

import pytest

from shipit_agent import Agent, AgentHooks, FunctionTool
from shipit_agent.models import ToolResult, ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.base import ToolOutput


def test_chained_hooks_validate_rewritten_arguments():
    hooks = AgentHooks()
    hooks.on_before_tool(lambda n, a: {"decision": "allow", "updated_arguments": {"path": "blocked"}})
    hooks.on_before_tool(lambda n, a: False if a["path"] == "blocked" else None)
    assert hooks.run_before_tool("write", {"path": "safe"}).denied


def test_approval_cannot_be_erased_by_later_rewrite():
    hooks = AgentHooks()
    hooks.on_before_tool(lambda n, a: {"decision": "ask", "reason": "review"})
    hooks.on_before_tool(lambda n, a: {"decision": "allow", "updated_arguments": {"value": 2}})
    result = hooks.run_before_tool("write", {"value": 1})
    assert result.needs_approval and result.updated_arguments == {"value": 2}


def test_async_policy_is_rejected_not_silently_ignored():
    hooks = AgentHooks()
    @hooks.on_before_tool_matching("write*")
    async def deny(name, args):
        return False
    with pytest.raises(TypeError, match="synchronous"):
        hooks.run_before_tool("write_file", {})


@pytest.mark.parametrize("replacement", ["redacted", {"output": "redacted"}, ToolOutput(text="redacted")])
def test_replacing_output_clears_stale_model_view(replacement):
    hooks = AgentHooks(after_tool=[lambda n, r: replacement])
    result = hooks.run_after_tool("lookup", ToolResult(name="lookup", output="SECRET", model_text="SECRET"))
    assert result.output == "redacted"
    assert result.model_text is None


@pytest.mark.parametrize("mode", ["run", "stream", "arun", "astream"])
def test_custom_hooks_work_across_agent_entrypoints(mode):
    calls = []
    seen = []
    hooks = AgentHooks()
    hooks.on_user_prompt(lambda p: p.replace("PRIVATE", "public"))
    hooks.on_before_tool_matching("lookup")(lambda n, a: {
        "decision": "allow", "updated_arguments": {"query": "scoped"}})
    hooks.on_after_tool_matching("lookup")(lambda n, r: "safe evidence")
    def lookup(query: str):
        calls.append(query)
        return ToolOutput(text="SECRET", model_text="SECRET")
    class Model:
        count = 0
        def complete(self, *, messages, **kwargs):
            seen.extend(messages)
            self.count += 1
            if self.count == 1:
                return LLMResponse(tool_calls=[ToolCall(name="lookup", arguments={"query": "original"})])
            assert any(m.role == "tool" and m.content == "safe evidence" for m in messages)
            return LLMResponse(content="done")
    agent = Agent(llm=Model(), tools=[FunctionTool.from_callable(lookup)], hooks=hooks,
                  auto_use_skills=False, auto_project_memory=False, auto_project_skills=False)
    async def async_run():
        if mode == "arun":
            await agent.arun("PRIVATE")
        else:
            async for _ in agent.astream("PRIVATE"):
                pass
    if mode == "run":
        agent.run("PRIVATE")
    elif mode == "stream":
        list(agent.stream("PRIVATE"))
    else:
        asyncio.run(async_run())
    assert calls == ["scoped"]
    assert all("SECRET" not in str(m.content) and "PRIVATE" not in str(m.content) for m in seen)
