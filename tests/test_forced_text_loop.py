"""A model that keeps calling a tool after tools were switched off must not loop.

Found live: a small model passed bad arguments to a no-argument tool, then
called it again on every step. Repeats were suppressed, the tool withheld and
the next step sent with no tools at all, yet the model still emitted the call,
which was processed and re-armed the same cycle until max_iterations: 16 model
calls and ~70k tokens for a one-line answer.
"""

from __future__ import annotations

import asyncio

from shipit_agent.async_runtime import AsyncAgentRuntime
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolOutput


class ListDocs:
    name = "list_documents"
    description = "List the user's documents. Takes no arguments."
    prompt_instructions = ""

    def schema(self):
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": {}}}}

    def run(self, context, **kwargs):
        if kwargs:
            return ToolOutput(text="list_documents failed: unexpected keyword argument 'name'")
        return ToolOutput(text="no documents")


class Stubborn:
    """Always calls the tool, whatever it is offered."""

    def __init__(self):
        self.calls = 0
        self.tools_offered: list[int] = []

    def complete(self, *, messages, tools=None, **_):
        self.calls += 1
        self.tools_offered.append(len(tools or []))
        return LLMResponse(content='{"name": "Asha"}',
                           tool_calls=[ToolCall(name="list_documents", arguments={"name": "Asha"})])


def test_calls_on_a_text_only_step_are_ignored_and_the_run_ends():
    llm = Stubborn()
    runtime = AgentRuntime(llm=llm, prompt="p", tools=[ListDocs()], max_iterations=16)
    state, response = runtime.run("Return my details as JSON")
    assert llm.calls <= 4
    assert response.content == '{"name": "Asha"}'
    assert 0 in llm.tools_offered
    assert any(e.type == "tool_calls_ignored" for e in state.events)


def test_the_async_runtime_ends_too():
    llm = Stubborn()
    runtime = AsyncAgentRuntime(llm=llm, prompt="p", tools=[ListDocs()], max_iterations=16)
    state, response = asyncio.run(runtime.run("Return my details as JSON"))
    assert llm.calls <= 4
    assert response.content == '{"name": "Asha"}'
