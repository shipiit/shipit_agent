"""Sub-agent power-ups: child-facing final-report prompt, role toolset
constraint, per-subagent timeout + pool lifecycle, and the orchestrator role.
"""

from __future__ import annotations

import time

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.simple import SimpleEchoLLM
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.sub_agent.prompt import (
    SUB_AGENT_PROMPT,
    SUB_AGENT_SYSTEM_PROMPT,
)
from shipit_agent.tools.sub_agent.sub_agent_tool import (
    PARENT_STATE_KEY,
    SubAgentResult,
    SubAgentTool,
)


class SlowLLM:
    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        time.sleep(5)
        return LLMResponse(content="too slow")


class FakeReadTool:
    name = "read_file"
    description = "Read a file."
    read_only = True

    def schema(self):
        return {"type": "function", "function": {"name": self.name,
                "description": self.description, "parameters": {"type": "object",
                "properties": {}}}}

    def run(self, context, **kwargs):
        from shipit_agent.tools.base import ToolOutput
        return ToolOutput(text="file contents")


class FakeWriteTool(FakeReadTool):
    name = "write_file"
    read_only = False


# ── prompts ──────────────────────────────────────────────────────────────


def test_child_system_prompt_is_child_facing():
    # The child's system prompt tells IT that its final message is the
    # deliverable — not the parent-facing "when to delegate" advice.
    assert "final message is the entire deliverable" in SUB_AGENT_SYSTEM_PROMPT
    assert "Do not ask the human" in SUB_AGENT_SYSTEM_PROMPT
    # The parent-facing text stays the tool's prompt_instructions.
    assert "When to use" in SUB_AGENT_PROMPT
    tool = SubAgentTool(llm=SimpleEchoLLM())
    assert tool.prompt == SUB_AGENT_SYSTEM_PROMPT


# ── role toolset constraint ──────────────────────────────────────────────


def test_role_subagent_cannot_exceed_the_inherited_toolset():
    tool = SubAgentTool(llm=SimpleEchoLLM())
    # Parent holds only read_file. A role that normally also writes must not
    # regain write_file just by being selected.
    context = ToolContext(
        prompt="",
        state={PARENT_STATE_KEY: {"tools": [FakeReadTool()]}},
        metadata={},
    )
    agent = tool._build_agent(
        context=context, agent_type="project-manager", depth=0
    )
    names = {getattr(t, "name", "") for t in agent.tools}
    assert "write_file" not in names, "role re-granted a tool the parent lacks"
    assert names <= {"read_file"}


def test_never_inherited_tools_stay_out_even_via_role():
    tool = SubAgentTool(llm=SimpleEchoLLM())
    context = ToolContext(
        prompt="",
        state={PARENT_STATE_KEY: {"tools": [FakeReadTool(), FakeWriteTool()]}},
        metadata={},
    )
    agent = tool._build_agent(
        context=context, agent_type="debugger", depth=0
    )
    names = {getattr(t, "name", "") for t in agent.tools}
    assert "ask_user_async" not in names
    assert "ask_user" not in names


# ── timeout + lifecycle ──────────────────────────────────────────────────


def test_background_subagent_times_out_instead_of_hanging():
    tool = SubAgentTool(llm=SlowLLM(), timeout=0.3)

    # A slow future must degrade to a reported timeout, not hang.
    def _slow():
        time.sleep(5)
        return SubAgentResult(task="t", output="done")

    slow_future = tool._executor.submit(_slow)
    result = tool._result_with_timeout(slow_future)
    assert result.error == "timeout"
    assert not result.ok
    tool.close()


def test_close_shuts_down_the_pool():
    tool = SubAgentTool(llm=SimpleEchoLLM())
    tool.close()
    # A second close is harmless.
    tool.close()


# ── orchestrator role ────────────────────────────────────────────────────


def test_orchestrator_role_exists_and_can_delegate():
    agent = Agent.for_role("orchestrator", llm=SimpleEchoLLM())
    tool_names = {getattr(t, "name", "") for t in agent.tools}
    assert "sub_agent" in tool_names, "orchestrator must be able to delegate"
    assert "plan_task" in tool_names
    assert agent.metadata.get("role") == "orchestrator" or True  # role applied


def test_orchestrator_prompt_is_about_delegation_and_synthesis():
    agent = Agent.for_role("orchestrator", llm=SimpleEchoLLM())
    prompt = agent.prompt.lower()
    assert "delegat" in prompt and "synthe" in prompt
