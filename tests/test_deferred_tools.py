"""Deferred tool loading — core schemas resident, the rest loaded on demand.

Covers the shared decision (RuntimeCore) through both loops:
- step 1 advertises core tools only; deferred tools appear by NAME in the
  system-prompt index;
- tool_search loads matching deferred tools, whose schemas ride along on
  every later step;
- calling a deferred tool directly still works and loads it;
- pure selection helpers behave for every config shape.
"""

from __future__ import annotations

import asyncio

from shipit_agent.agent import Agent
from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.deferral import (
    DEFAULT_CORE_TOOLS,
    deferred_index,
    resolve_deferred_names,
    select_schemas,
    signature_line,
)
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool


class ScriptedLLM:
    """Replays a scripted conversation, recording what it was shown."""

    def __init__(self, script):
        self.script = list(script)
        self.seen_tools: list[list[str]] = []
        self.seen_system: list[str] = []

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.seen_tools.append(
            [((t.get("function") or {}).get("name")) for t in (tools or [])]
        )
        self.seen_system.append(system_prompt or "")
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
            usage={"total_tokens": 10},
        )


class FakeTool:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }

    def run(self, context, **kwargs) -> ToolOutput:
        return ToolOutput(text=f"{self.name} ran", metadata={})


def make_tools():
    return [
        ToolSearchTool(),
        FakeTool("slack_send", "Send a message to a Slack channel."),
        FakeTool("jira_create", "Create a Jira issue in a project."),
    ]


def make_runtime(llm, **kwargs):
    return AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=make_tools(),
        deferred_tools=True,
        max_iterations=4,
        **kwargs,
    )


# ── pure helpers ─────────────────────────────────────────────────────────


def test_resolve_defers_non_core_and_never_tool_search():
    tools = make_tools()
    deferred = resolve_deferred_names(tools, True)
    assert deferred == {"slack_send", "jira_create"}
    # explicit list defers exactly those; unknown names ignored
    assert resolve_deferred_names(tools, ["slack_send", "ghost"]) == {"slack_send"}
    # tool_search can never defer itself
    assert "tool_search" not in resolve_deferred_names(tools, ["tool_search"])
    assert resolve_deferred_names(tools, False) == set()


def test_select_schemas_core_plus_loaded():
    schemas = [t.schema() for t in make_tools()]
    deferred = {"slack_send", "jira_create"}
    names = lambda s: [(x.get("function") or {}).get("name") for x in s]  # noqa: E731
    assert names(select_schemas(schemas, deferred, set())) == ["tool_search"]
    assert names(select_schemas(schemas, deferred, {"slack_send"})) == [
        "tool_search",
        "slack_send",
    ]
    # deferral off → unchanged
    assert names(select_schemas(schemas, set(), set())) == names(schemas)


def test_index_lists_names_only():
    tools = make_tools()
    index = deferred_index(tools, {"slack_send", "jira_create"})
    assert "slack_send" in index and "jira_create" in index
    assert "tool_search" in index  # tells the model how to load
    # no schema payloads in the index
    assert "properties" not in index


def test_signature_line_marks_optional_args():
    schema = {
        "type": "function",
        "function": {
            "name": "send",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "thread": {"type": "string"},
                },
                "required": ["channel"],
            },
        },
    }
    assert signature_line(schema) == "send(channel: string, thread?: string)"


# ── sync loop ────────────────────────────────────────────────────────────


def test_search_then_call_loads_schema_mid_run():
    llm = ScriptedLLM(
        [
            ("searching", [("tool_search", {"query": "send slack message"})]),
            ("sending", [("slack_send", {"text": "release is out"})]),
            ("done", []),
        ]
    )
    runtime = make_runtime(llm)
    state, response = runtime.run("Announce the release on slack")

    # Step 1: core only — deferred schemas withheld, names in the prompt.
    assert "slack_send" not in llm.seen_tools[0]
    assert "tool_search" in llm.seen_tools[0]
    assert "slack_send" in llm.seen_system[0]

    # Step 2: the search loaded slack_send; its schema is now advertised.
    assert "slack_send" in llm.seen_tools[1]

    # The search result told the model what it loaded, with a signature.
    search_result = next(r for r in state.tool_results if r.name == "tool_search")
    assert "slack_send" in search_result.output
    assert "slack_send" in (search_result.metadata.get("loaded") or [])

    assert response.content == "done"


def test_direct_call_to_deferred_tool_still_works_and_loads_it():
    llm = ScriptedLLM(
        [
            ("going direct", [("jira_create", {"text": "bug"})]),
            ("done", []),
        ]
    )
    runtime = make_runtime(llm)
    state, response = runtime.run("File a jira issue")

    executed = [r.name for r in state.tool_results]
    assert "jira_create" in executed
    # Once called, the schema is advertised on the following step.
    assert "jira_create" in llm.seen_tools[1]
    assert response.content == "done"


def test_deferral_off_keeps_everything_resident():
    llm = ScriptedLLM([("done", [])])
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=make_tools(),
        deferred_tools=False,
        max_iterations=4,
    )
    runtime.run("hello")
    assert "slack_send" in llm.seen_tools[0]
    assert "jira_create" in llm.seen_tools[0]


def test_core_tools_stay_resident_when_present():
    class CoreFake(FakeTool):
        pass

    core_name = sorted(DEFAULT_CORE_TOOLS)[0]
    llm = ScriptedLLM([("done", [])])
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=[*make_tools(), CoreFake(core_name, "A core tool.")],
        deferred_tools=True,
        max_iterations=4,
    )
    runtime.run("hello")
    assert core_name in llm.seen_tools[0]
    assert "slack_send" not in llm.seen_tools[0]


# ── async loop parity ────────────────────────────────────────────────────


def test_async_loop_defers_and_loads_identically():
    llm = ScriptedLLM(
        [
            ("searching", [("tool_search", {"query": "send slack message"})]),
            ("sending", [("slack_send", {"text": "release is out"})]),
            ("done", []),
        ]
    )
    runtime = AsyncAgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=make_tools(),
        deferred_tools=True,
        max_iterations=4,
    )
    state, response = asyncio.run(runtime.run("Announce the release on slack"))

    assert "slack_send" not in llm.seen_tools[0]
    assert "slack_send" in llm.seen_system[0]
    assert "slack_send" in llm.seen_tools[1]
    assert response.content == "done"


# ── Agent-level threading ────────────────────────────────────────────────


def test_agent_threads_deferred_tools_option():
    llm = ScriptedLLM([("done", [])])
    agent = Agent(
        llm=llm,
        tools=make_tools(),
        deferred_tools=True,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
    )
    result = agent.run("hello")
    assert result.output == "done"
    assert "slack_send" not in llm.seen_tools[0]
    assert "slack_send" in llm.seen_system[0]


def test_deferred_selection_preserves_provider_schema_shape():
    """Deferral filters WHICH schemas are sent, never their format.

    Every provider adapter (OpenAI, Anthropic, Bedrock, LiteLLM…) receives
    the same wrapped ``{"type": "function", "function": ...}`` dicts it
    would without deferral — so the mechanism is provider-agnostic by
    construction. This asserts the surviving schemas are byte-identical to
    the registry's own output, at every stage of loading.
    """
    schemas = [t.schema() for t in make_tools()]
    deferred = {"slack_send", "jira_create"}
    for loaded in (set(), {"slack_send"}, {"slack_send", "jira_create"}):
        for selected in select_schemas(schemas, deferred, loaded):
            assert selected in schemas  # same objects, no reshaping
            assert selected.get("type") == "function"
            fn = selected["function"]
            assert fn["name"] and fn["description"]
            assert fn["parameters"]["type"] == "object"


def test_code_mode_wins_over_deferral():
    llm = ScriptedLLM([("done", [])])
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=make_tools(),
        deferred_tools=True,
        code_mode=True,
        max_iterations=4,
    )
    runtime.run("hello")
    # Code mode's own collapse applies; the deferral index must not be
    # layered on top of it (setup_deferral is a no-op under code mode).
    assert "not loaded yet" not in llm.seen_system[0]
