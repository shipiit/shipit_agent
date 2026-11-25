"""A hook that replaces a tool's output replaces what the model is sent, not only what is shown."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall, ToolResult
from shipit_agent.hooks import AgentHooks
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.base import ToolOutput

SECRET = "api_key=SECRET-123"


def _result() -> ToolResult:
    return ToolResult(name="lookup", output=SECRET, model_text=SECRET,
                      metadata={"image_base64": "aGk=", "media_type": "image/png", "vision": True})


@pytest.mark.parametrize("replacement", ["[redacted]", {"output": "[redacted]"}, {"text": "[redacted]"}, ToolOutput(text="[redacted]")])
def test_every_way_an_after_tool_hook_replaces_output_clears_the_model_view(replacement: Any) -> None:
    hooks = AgentHooks(after_tool=[lambda name, result: replacement])
    result = hooks.run_after_tool("lookup", _result())
    assert result.output == "[redacted]" and result.model_text is None
    assert "image_base64" not in result.metadata and "vision" not in result.metadata


def test_a_replacement_that_brings_its_own_model_view_keeps_it() -> None:
    hooks = AgentHooks(after_tool=[lambda name, result: ToolOutput(text="[redacted]", model_text="short [redacted]")])
    assert hooks.run_after_tool("lookup", _result()).model_text == "short [redacted]"


def test_a_post_tool_use_replacement_clears_it_and_added_context_reaches_the_model() -> None:
    hooks = AgentHooks()
    hooks.post_tool_use.append(lambda name, arguments, result: {"updated_output": "[redacted]"})
    result = hooks.run_after_tool("lookup", _result(), {})
    assert (result.output, result.model_text) == ("[redacted]", None)
    noted = AgentHooks()
    noted.post_tool_use.append(lambda name, arguments, result: {"additional_context": "Checked."})
    kept = noted.run_after_tool("lookup", ToolResult(name="lookup", output="full", model_text="short"), {})
    assert kept.output.endswith("Checked.") and kept.model_text.endswith("Checked.")


def test_a_hook_that_only_adds_metadata_leaves_the_model_view_alone() -> None:
    hooks = AgentHooks(after_tool=[lambda name, result: {"metadata": {"seen": True}}])
    result = hooks.run_after_tool("lookup", _result())
    assert result.model_text == SECRET and result.metadata["seen"] is True


def _secret_tool(query: str = "") -> ToolOutput:
    """Look something up."""
    return ToolOutput(text=SECRET, model_text=SECRET)


class _Model:
    model = "m"

    def __init__(self) -> None:
        self.turn, self.seen = 0, []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.turn += 1
        self.seen.extend(str(m.content) for m in messages)
        if self.turn == 1:
            return LLMResponse(tool_calls=[ToolCall(name="lookup", arguments={"query": "x"}, id="c1")])
        return LLMResponse(content="done")


def test_in_a_run_the_model_never_receives_the_redacted_secret() -> None:
    model = _Model()
    hooks = AgentHooks()
    hooks.on_after_tool_matching("lookup")(lambda name, result: "[redacted]")
    Agent(llm=model, tools=[FunctionTool.from_callable(_secret_tool, name="lookup")], hooks=hooks).run("go")
    assert not any("SECRET-123" in text for text in model.seen)
    assert any("[redacted]" in text for text in model.seen)


def test_through_the_sdk_a_post_tool_use_redaction_reaches_the_model() -> None:
    from shipit_agent.sdk import AgentOptions, HookMatcher, query

    model = _Model()

    def redact(payload: dict[str, Any], tool_use_id: Any, context: Any) -> dict[str, Any]:
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": "[redacted]"}}

    options = AgentOptions(llm=model, tools=[FunctionTool.from_callable(_secret_tool, name="lookup")], allowed_tools=["lookup"],
                           hooks={"PostToolUse": [HookMatcher(matcher="lookup", hooks=[redact])]})

    async def go() -> None:
        async for _ in query(prompt="go", options=options):
            pass

    asyncio.run(go())
    assert not any("SECRET-123" in text for text in model.seen)
