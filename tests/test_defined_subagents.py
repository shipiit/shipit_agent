"""User-defined sub-agents, as in the Claude Agent SDK.

``Agent(agents={...})`` and ``.shipit/agents/*.md`` / ``.claude/agents/*.md``
files define named sub-agents: a description of when to use one, its own
prompt, an optional tool list and an optional model. The agent then has a
``sub_agent`` tool that lists them; a child gets its definition's prompt and
never more tools than its parent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.agents.subagent_definitions import (
    SubagentDefinition,
    coerce_subagents,
    load_subagent_files,
)
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse


def _read(path: str = "") -> str:
    """Read something."""
    return f"read {path}"


def _write(path: str = "") -> str:
    """Write something."""
    return f"wrote {path}"


TOOLS = [
    FunctionTool.from_callable(_read, name="read_file"),
    FunctionTool.from_callable(_write, name="write_file"),
]


class _Delegates:
    """Parent: delegates once to *agent_type*, then answers. Child: answers."""

    model = "claude-sonnet-5-5"

    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        self.requests: list[dict[str, Any]] = []

    def complete(
        self, *, messages: Any, tools: Any = None, system_prompt: Any = None, **_: Any
    ) -> LLMResponse:
        system = next(
            (m.content for m in messages if m.role == "system"), system_prompt or ""
        )
        self.requests.append(
            {"system": system, "tools": [t["function"]["name"] for t in tools or []]}
        )
        if "You review code" in system:
            return LLMResponse(content="Looks good; one nit.")
        if any(m.role == "tool" for m in messages):
            return LLMResponse(content="Review done.")
        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    name="sub_agent",
                    arguments={"task": "Review app.py", "agent_type": self.agent_type},
                )
            ],
        )


REVIEWER = {
    "description": "Use for reviewing code changes.",
    "prompt": "You review code. Be specific.",
    "tools": ["read_file"],
}


def test_definitions_accept_dicts_and_objects() -> None:
    agents = coerce_subagents(
        {
            "reviewer": REVIEWER,
            "writer": SubagentDefinition("Use to draft docs.", "You write docs."),
        }
    )
    assert agents["reviewer"].tools == ["read_file"]
    assert agents["writer"].tools is None
    assert agents["writer"].model is None


@pytest.mark.parametrize(
    "bad", [{"x": {"prompt": "no description"}}, {"": REVIEWER}, {"x": 3}]
)
def test_bad_definitions_are_refused(bad: Any) -> None:
    with pytest.raises(ValueError):
        coerce_subagents(bad)


def test_agent_files_are_read_from_shipit_and_claude_folders() -> None:
    root = Path(tempfile.mkdtemp())
    (root / ".claude" / "agents").mkdir(parents=True)
    (root / ".claude" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Use for reviewing code.\ntools: read_file, grep_files\n"
        "model: claude-haiku-5-5\n---\nYou review code.\n"
    )
    (root / ".shipit" / "agents").mkdir(parents=True)
    (root / ".shipit" / "agents" / "writer.md").write_text(
        "---\ndescription: Use to draft docs.\n---\nYou write docs.\n"
    )
    agents = load_subagent_files(root)
    assert agents["reviewer"].tools == ["read_file", "grep_files"]
    assert agents["reviewer"].model == "claude-haiku-5-5"
    assert agents["writer"].prompt == "You write docs."


def test_defining_agents_adds_a_sub_agent_tool_that_lists_them() -> None:
    agent = Agent(
        llm=_Delegates("reviewer"), tools=TOOLS, agents={"reviewer": REVIEWER}
    )
    tool = next(t for t in agent._effective_tools("go") if t.name == "sub_agent")
    described = str(tool.schema())
    assert "reviewer" in described and "reviewing code changes" in described


def test_no_definitions_means_no_sub_agent_tool() -> None:
    agent = Agent(
        llm=_Delegates("reviewer"), tools=TOOLS, project_root=tempfile.mkdtemp()
    )
    assert "sub_agent" not in {t.name for t in agent._effective_tools("go")}


def test_a_defined_child_runs_with_its_prompt_and_only_its_tools() -> None:
    llm = _Delegates("reviewer")
    agent = Agent(
        llm=llm,
        tools=TOOLS,
        agents={"reviewer": REVIEWER},
        project_root=tempfile.mkdtemp(),
    )

    result = agent.run("Get app.py reviewed")

    child = next(r for r in llm.requests if "You review code" in r["system"])
    assert child["tools"] == ["read_file"]
    assert result.output == "Review done."


def test_a_child_never_gets_tools_its_parent_lacks() -> None:
    llm = _Delegates("reviewer")
    definition = {**REVIEWER, "tools": ["read_file", "bash"]}
    agent = Agent(
        llm=llm,
        tools=TOOLS[:1],
        agents={"reviewer": definition},
        project_root=tempfile.mkdtemp(),
    )
    agent.run("Get app.py reviewed")
    child = next(r for r in llm.requests if "You review code" in r["system"])
    assert child["tools"] == ["read_file"]


def test_a_definitions_model_is_used_for_the_child() -> None:
    llm = _Delegates("reviewer")
    agent = Agent(
        llm=llm,
        tools=TOOLS,
        agents={"reviewer": {**REVIEWER, "model": "claude-haiku-5-5"}},
        project_root=tempfile.mkdtemp(),
    )
    tool = next(t for t in agent._effective_tools("go") if t.name == "sub_agent")
    child_llm = tool.llm_for(tool.agents["reviewer"])
    assert child_llm.model == "claude-haiku-5-5"
    assert llm.model == "claude-sonnet-5-5"
