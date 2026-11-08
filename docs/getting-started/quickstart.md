---
description: Run your first agent, watch it work, give it a tool of your own, and use the SDK API.
---

# Quickstart

In five minutes you will run an agent, stream what it does, add a tool of your own, and run the same agent through the Claude Agent SDK API.

## 1. Install and set a key

```bash
pip install 'shipit-agent[anthropic]'
export SHIPIT_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

Any provider works; [Configure a model](environment.md) lists them.

## 2. Run an agent

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env

agent = Agent.with_builtins(llm=build_llm_from_env(), project_root=".")
result = agent.run("Find the TODO comments in this project and group them by file.")
print(result.output)
```

`Agent.with_builtins()` gives the agent the built-in tools: reading and searching files, editing, bash, the web, a todo list, sub-agents and more. `project_root` is the folder the file tools and bash work in; they refuse paths outside it.

`result` is an `AgentResult`. Besides `output`, it has every message, every event and every tool result. `result.metadata["usage"]` holds the token counts, and `result.metadata["run_summary"]` how the run went, including `estimated_cost_usd`.

## 3. Watch it work

`stream()` runs the same loop and yields events as they happen:

```python
for event in agent.stream("Find the TODO comments in this project."):
    print(f"{event.type:22} {event.message}")
```

```text
run_started            Agent run started
step_started           LLM completion started
assistant_message      Model response
tool_called            Tool called: grep_files
tool_completed         Tool completed: grep_files
step_started           LLM completion started
assistant_message      Model response
final_answer           Final answer generated
run_summary            Run finished: 2 iterations, 1 tool calls
run_completed          Agent run completed
```

Each event has a `type`, a `message` and a `payload` with the details: the tool's arguments, its output, token counts. `text_delta` events carry the answer as it is written. [Streaming](../agent/streaming.md) covers them all.

## 4. Give it your own tool

Any function becomes a tool. Its name, docstring and type hints become the schema the model sees.

```python
from shipit_agent import Agent
from shipit_agent.llms import build_llm_from_env
from shipit_agent.tools import FunctionTool


def order_status(order_id: str) -> str:
    """Look up an order's shipping status by its id."""
    return f"{order_id}: shipped on 3 November, tracking ZX-9917"


agent = Agent(
    llm=build_llm_from_env(),
    tools=[FunctionTool.from_callable(order_status, read_only=True)],
)
print(agent.run("Where is order A-1043?").output)
```

`read_only=True` tells the permission system the tool changes nothing, so it never needs approval. [Custom tools](../guides/custom-tools.md) covers tool classes, rich output and errors.

## 5. The same agent, through the SDK API

If you know the Claude Agent SDK, this is its API. `query()` yields typed messages and ends with a `ResultMessage`.

```python
import asyncio

from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, TextBlock, query


async def main() -> None:
    options = AgentOptions(
        model="claude-sonnet-5-5",
        cwd=".",
        permission_mode="acceptEdits",
        max_turns=20,
    )
    async for message in query(prompt="Fix the failing test in tests/", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(message.subtype, message.num_turns, "turns", f"${message.total_cost_usd:.4f}")


asyncio.run(main())
```

`permission_mode="acceptEdits"` lets the agent edit files without asking; commands that delete files, push or reach outside the project still need approval. [Permissions](../guides/permissions.md) explains the modes.

## Next

- [Core concepts](concepts.md): how the loop, tools, permissions and context fit together.
- [Tools](../agent/with-tools.md): what each built-in tool does.
- [Agent SDK API](../guides/agent-sdk.md): every option and message.
- [Examples](../agent/examples.md): complete agents to copy.
