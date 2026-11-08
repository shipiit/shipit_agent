---
description: Test agents and tools without calling a real model, with a scripted model, direct tool calls and event assertions.
---

# Testing agents

An agent's model is just an object with a `complete()` method. Give the agent one that returns scripted responses, and the whole loop (tool calls, permissions, hooks, events) runs in your tests without a network or a bill.

## A scripted model

```python
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall


class ScriptedLLM:
    """Returns the given responses in order, one per model call."""

    model = "scripted"

    def __init__(self, *responses: LLMResponse) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete(self, *, messages, **kwargs) -> LLMResponse:
        self.calls.append(messages)
        return self.responses.pop(0)
```

Each `LLMResponse` is one model turn: `content` for text, `tool_calls` for calls.

## Testing that the agent calls the right tool

```python
from shipit_agent import Agent
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools import FunctionTool


def order_status(order_id: str) -> str:
    """The shipping status of an order."""
    return f"{order_id}: delivered"


def test_the_agent_looks_up_the_order() -> None:
    llm = ScriptedLLM(
        LLMResponse(tool_calls=[ToolCall(name="order_status", arguments={"order_id": "A-1043"})]),
        LLMResponse(content="Your order A-1043 was delivered."),
    )
    agent = Agent(llm=llm, tools=[FunctionTool.from_callable(order_status, read_only=True)])

    result = agent.run("Where is A-1043?")

    assert result.tool_results[0].output == "A-1043: delivered"
    assert result.output == "Your order A-1043 was delivered."
```

The second model call saw the tool's result: `llm.calls[1]` holds the messages it received, so you can assert on exactly what the model was shown.

## Testing a tool on its own

A tool is ordinary code; call `run()` with a context.

```python
from shipit_agent.tools.base import ToolContext


def test_refund_rejects_a_bad_order_id() -> None:
    out = RefundTool().run(ToolContext(prompt=""), order_id="1043")
    assert "Order ids look like A-1043" in out.text
```

## Testing permissions and hooks

Script a risky call and check that it was refused, not run:

```python
from shipit_agent import Agent
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.tools import BashTool


def test_deleting_needs_approval(tmp_path) -> None:
    (tmp_path / "keep.txt").write_text("data")
    llm = ScriptedLLM(
        LLMResponse(tool_calls=[ToolCall(name="bash", arguments={"command": "rm keep.txt"})]),
        LLMResponse(content="I could not delete it."),
    )
    agent = Agent(llm=llm, tools=[BashTool(root_dir=tmp_path)], project_root=tmp_path)

    result = agent.run("Delete keep.txt")

    assert (tmp_path / "keep.txt").exists()
    assert any(e.type == "tool_denied" for e in result.events)
```

## Testing what streams

`result.events` holds every event in order, the same ones `stream()` yields:

```python
types = [event.type for event in result.events]
assert types[0] == "run_started" and types[-1] == "run_completed"
assert "tool_called" in types
```

## Keep tests fast and isolated

- Turn off what reads the machine: `auto_project_memory=False`, `auto_project_skills=False`, `auto_use_skills=False`.
- Use `tmp_path` for `project_root` and for any file store.
- Test with a real model separately and rarely. The [benchmark](benchmark.md) runs 18 real tasks and reports passes, turns, tokens and cost.
