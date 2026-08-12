"""Native `response_format` is applied on the tool-less final turn only —
never mid-loop (JSON-mode would suppress tool calls), and only for adapters
that accept it.
"""

from __future__ import annotations

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools.base import ToolOutput


class FormatRecordingLLM:
    """Records the `response_format` seen on each completion."""

    def __init__(self, script):
        self.script = list(script)
        self.formats: list = []

    def complete(
        self,
        *,
        messages,
        tools=None,
        system_prompt=None,
        metadata=None,
        response_format=None,
    ):
        self.formats.append(response_format)
        text, calls = self.script.pop(0) if self.script else ('{"answer": "x"}', [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


class NoFormatLLM:
    """An adapter that does NOT accept response_format — must never get it."""

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        return LLMResponse(content='{"answer": "ok"}')


class ReadTool:
    name = "read_file"
    description = "Read."
    read_only = True

    def schema(self):
        return {"type": "function", "function": {"name": self.name,
                "description": "Read.", "parameters": {"type": "object",
                "properties": {}}}}

    def run(self, context, **kwargs):
        return ToolOutput(text="data")


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"]}


def _agent(llm, **kw):
    return Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=3,
        **kw,
    )


def test_response_format_applied_only_when_no_tools_are_sent():
    # Turn 1 calls a tool (tools present → no format); turn 2 is the answer.
    llm = FormatRecordingLLM(
        [("", [("read_file", {})]), ('{"answer": "done"}', [])]
    )
    _agent(llm, tools=[ReadTool()]).run("go", output_schema=SCHEMA)
    # First completion sent tools → response_format must be absent.
    assert llm.formats[0] is None
    # A later tool-less completion carries the native format.
    assert any(f is not None for f in llm.formats[1:])


def test_no_tools_agent_gets_format_on_the_only_turn():
    llm = FormatRecordingLLM([('{"answer": "hi"}', [])])
    _agent(llm).run("just answer", output_schema=SCHEMA)
    assert llm.formats[-1] is not None
    assert llm.formats[-1]["type"] in ("json_object", "json_schema")


def test_adapter_without_response_format_never_receives_it():
    # NoFormatLLM.complete has no response_format param — must not raise.
    result = _agent(NoFormatLLM()).run("answer", output_schema=SCHEMA)
    assert result.output  # ran cleanly


def test_without_output_schema_no_format_is_sent():
    llm = FormatRecordingLLM([("plain answer", [])])
    _agent(llm).run("hello")
    assert all(f is None for f in llm.formats)
