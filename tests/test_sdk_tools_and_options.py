"""``@tool``, ``create_sdk_mcp_server`` and how ``AgentOptions`` builds an Agent."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.sdk import AgentOptions, ResultMessage, UserMessage, build_agent, create_sdk_mcp_server, query, tool
from shipit_agent.sdk import build as build_module
from shipit_agent.sdk.build import mcp_servers, system_prompt
from shipit_agent.sdk.options import DEFAULT_TOOLS


class _Calls:
    model = "claude-sonnet-5-5"

    def __init__(self, *calls: tuple[str, dict[str, Any]]) -> None:
        self.calls = list(calls)
        self.system = ""

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.system = next((m.content for m in messages if m.role == "system"), "")
        if self.calls:
            name, arguments = self.calls.pop(0)
            return LLMResponse(content="", tool_calls=[ToolCall(name=name, arguments=arguments, id="c1")])
        return LLMResponse(content="done")


@tool("add", "Add two numbers", {"a": float, "b": float})
async def add(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": str(args["a"] + args["b"])}]}


@tool("fail", "Always fails", {"type": "object", "properties": {}})
def fail(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "quota exceeded"}], "is_error": True}


CALC = create_sdk_mcp_server("calc", tools=[add, fail])


def _messages(**options: Any) -> list[Any]:
    async def run() -> list[Any]:
        return [m async for m in query(prompt="go", options=AgentOptions(**options))]

    return asyncio.run(run())


# -- @tool and the in-process server --------------------------------------------


def test_a_type_mapping_becomes_a_json_schema() -> None:
    assert add.input_schema == {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }
    assert fail.input_schema == {"type": "object", "properties": {}}


def test_an_sdk_server_tool_runs_and_its_text_comes_back() -> None:
    messages = _messages(llm=_Calls(("calc__add", {"a": 2, "b": 3})), tools=[], mcp_servers={"calc": CALC})
    block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert (block.content, block.is_error) == ("5", False)


def test_a_tool_reporting_is_error_is_a_failed_result() -> None:
    messages = _messages(llm=_Calls(("calc__fail", {})), tools=[], mcp_servers={"calc": CALC})
    block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert block.is_error is True and block.content == "quota exceeded"


def test_an_sdk_style_allow_rule_names_the_server_tool() -> None:
    messages = _messages(
        llm=_Calls(("calc__add", {"a": 1, "b": 1})), tools=[], mcp_servers={"calc": CALC},
        allowed_tools=["mcp__calc__add"], permission_mode="dontAsk",
    )
    block = next(m for m in messages if isinstance(m, UserMessage)).content[0]
    assert block.content == "2"
    assert isinstance(messages[-1], ResultMessage) and messages[-1].permission_denials == []


# -- building the agent -----------------------------------------------------------


def test_without_tools_the_agent_gets_the_core_set(tmp_path: Path) -> None:
    agent = build_agent(AgentOptions(llm=_Calls(), cwd=tmp_path))
    assert sorted(t.name for t in agent.tools) == sorted(DEFAULT_TOOLS)


def test_sdk_tool_names_pick_built_ins(tmp_path: Path) -> None:
    agent = build_agent(AgentOptions(llm=_Calls(), cwd=tmp_path, tools=["Bash", "Read", "WebFetch"]))
    assert sorted(t.name for t in agent.tools) == ["bash", "open_url", "read_file"]


def test_all_gives_every_built_in(tmp_path: Path) -> None:
    agent = build_agent(AgentOptions(llm=_Calls(), cwd=tmp_path, tools="all"))
    assert len(agent.tools) > len(DEFAULT_TOOLS)


def test_an_unknown_tool_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Frobnicate"):
        build_agent(AgentOptions(llm=_Calls(), cwd=tmp_path, tools=["Frobnicate"]))


def test_options_land_on_the_agent(tmp_path: Path) -> None:
    agent = build_agent(AgentOptions(
        llm=_Calls(), cwd=tmp_path, tools=[], permission_mode="acceptEdits", max_turns=7,
        max_budget_usd=1.5, allowed_tools=["Read"], disallowed_tools=["Bash(rm *)"],
        session_id="s-1", agent_options={"name": "reviewer"},
    ))
    assert (agent.permission_mode, agent.max_iterations, agent.max_budget_usd) == ("acceptEdits", 7, 1.5)
    assert agent.allowed_tools == ["Read"] and agent.disallowed_tools == ["Bash(rm *)"]
    assert (agent.session_id, agent.name, Path(agent.project_root)) == ("s-1", "reviewer", tmp_path.resolve())


def test_effort_and_thinking_reach_an_adapter_that_takes_them(tmp_path: Path) -> None:
    llm = _Calls()
    llm.effort = None
    build_agent(AgentOptions(llm=llm, cwd=tmp_path, tools=[], effort="high", thinking="adaptive"))
    assert llm.effort == "high" and not hasattr(llm, "thinking")


@pytest.mark.parametrize(
    "model,provider",
    [("claude-opus-5-5", "anthropic"), ("anthropic/claude-opus-5-5", "anthropic"), ("gpt-5.5", "openai"),
     ("o4-mini", "openai"), ("bedrock/openai.gpt-oss-120b-1:0", "bedrock"), ("openrouter/x", "litellm")],
)
def test_a_model_id_picks_its_provider(model: str, provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[dict[str, Any], str]] = []
    from shipit_agent.llms import factory

    monkeypatch.setattr(factory, "build_llm_from_settings", lambda settings, provider: seen.append((settings, provider)))
    build_module.llm_for_model(model)
    assert seen[0][1] == provider
    assert not seen[0][0]["model"].startswith("anthropic/")


def test_system_prompt_forms(tmp_path: Path) -> None:
    from shipit_agent.prompts.default_agent_prompt import DEFAULT_AGENT_PROMPT

    assert system_prompt("Be brief.") == "Be brief."
    assert system_prompt(None) == DEFAULT_AGENT_PROMPT
    assert system_prompt({"type": "preset", "preset": "claude_code", "append": "Use tabs."}).endswith("Use tabs.")
    assert system_prompt({"type": "custom", "prompt": "Only SQL."}) == "Only SQL."
    path = tmp_path / "prompt.md"
    path.write_text("From a file.")
    assert system_prompt({"type": "file", "path": str(path)}) == "From a file."
    with pytest.raises(ValueError):
        system_prompt({"type": "nope"})


def test_the_system_prompt_reaches_the_model(tmp_path: Path) -> None:
    llm = _Calls()
    _messages(llm=llm, cwd=tmp_path, tools=[], system_prompt="You only speak in haiku.")
    assert "You only speak in haiku." in llm.system


def test_mcp_configs_become_servers() -> None:
    servers = mcp_servers({
        "calc": CALC,
        "files": {"type": "stdio", "command": "npx", "args": ["-y", "server-files"], "env": {"A": "1"}},
        "docs": {"type": "http", "url": "https://example.com/mcp", "headers": {"X": "y"}},
        "bare": {"command": "uvx", "args": ["thing"]},
    })
    assert [s.name for s in servers] == ["calc", "files", "docs", "bare"]
    assert servers[1].transport.command == ["npx", "-y", "server-files"]
    assert servers[1].include_server_in_tool_names is True
    assert servers[2].transport.endpoint == "https://example.com/mcp"


def test_an_unsupported_mcp_type_is_refused() -> None:
    with pytest.raises(ValueError, match="sse"):
        mcp_servers({"old": {"type": "sse", "url": "https://example.com/sse"}})


def test_output_format_must_be_a_json_schema() -> None:
    with pytest.raises(ValueError, match="json_schema"):
        AgentOptions(output_format={"type": "text"}).output_schema()
    assert AgentOptions().output_schema() is None
