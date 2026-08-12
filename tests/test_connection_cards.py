"""A connector without credentials produces the connection card — the
`/login` parity: a filed request, an instruction, and a run that continues.
"""

from __future__ import annotations

from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.runtime import AgentRuntime
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.slack.slack_tool import SlackTool


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


def test_unauthenticated_connector_emits_connection_requested_card():
    llm = ScriptedLLM(
        [
            ("posting", [("slack", {"action": "send_message", "channel": "#x", "text": "hi"})]),
            ("done", []),
        ]
    )
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=[SlackTool()],  # no credential store anywhere
        max_iterations=3,
    )
    state, response = runtime.run("tell slack")

    cards = [e for e in state.events if e.type == "connection_requested"]
    assert cards, "no connection_requested card was emitted"
    assert cards[0].payload["connection_id"] == "slack"
    assert cards[0].payload["reason"]

    # The model got an instruction, not a dead end.
    slack_results = [r for r in state.tool_results if r.name == "slack"]
    assert slack_results and "not connected" in slack_results[0].output
    assert slack_results[0].metadata.get("requested") is True
    # And the run completed instead of crashing.
    assert response.content == "done"


def test_without_registry_degrades_to_flat_text():
    tool = SlackTool()
    output = tool._not_connected_output(ToolContext(prompt="", state={}))
    assert "not connected" in output.text
    assert output.metadata.get("requested") is None
