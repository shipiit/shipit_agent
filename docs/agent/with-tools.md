---
title: Agent — With Tools
description: Extend an Agent with the built-in tool catalogue, custom Python functions, full Tool classes, and MCP servers.
---

# Agent — With Tools

Tools are how an `Agent` *does things*. Every tool is an object that
implements four members:

```python
class Tool(Protocol):
    name: str
    description: str
    prompt_instructions: str
    def schema(self) -> dict[str, Any]: ...
    def run(self, context: ToolContext, **kwargs: Any) -> ToolOutput: ...
```

`Agent` doesn't care where a tool comes from — anything implementing
that protocol works. This page walks through the four most common
shapes.

---

## 1. The built-in catalogue

`Agent.with_builtins()` ships ~30 tools out of the box:

```python
from shipit_agent import Agent

agent = Agent.with_builtins(llm=llm)
print([t.name for t in agent.tools])
# ['web_search', 'open_url', 'code_execution', 'workspace_files',
#  'plan_task', 'tool_search', 'sub_agent', 'verify_output',
#  'gmail', 'slack', 'jira', 'linear', 'notion', 'confluence',
#  'google_calendar', 'google_drive', 'playwright_browser', ...]
```

Highlights:

| Tool | What it does |
| --- | --- |
| `web_search` | Pluggable search providers (DuckDuckGo default; Brave, Tavily, Serper, Playwright) |
| `open_url` | Fetches a URL with the same provider's headless browser |
| `playwright_browser` | Full browser automation |
| `code_execution` | Runs untrusted Python in a subprocess |
| `workspace_files` | Read/write/list files in `.shipit_workspace` |
| `plan_task` | Planner — produces an ordered execution plan |
| `tool_search` | Search the tool registry by description |
| `sub_agent` | Spawn a fresh inner agent for a side-task |
| `gmail`, `slack`, `jira`, `linear`, `notion`, `confluence` | OAuth-aware connectors |

See the [Tools manifest](../reference/tools.md) for the full list with
parameter shapes.

---

## 2. Custom Python function as a tool

`FunctionTool.from_callable` reads the function's signature and
docstring and produces a fully-formed `Tool`:

```python
from shipit_agent import Agent
from shipit_agent.tools import FunctionTool

def get_weather(city: str, unit: str = "celsius") -> str:
    """Return the current weather for the given city.

    Args:
        city: City name (e.g., "Paris").
        unit: "celsius" or "fahrenheit".
    """
    return f"It's 18°{unit[0].upper()} in {city}."

agent = Agent(
    llm=llm,
    tools=[FunctionTool.from_callable(get_weather)],
)
agent.run("What's the weather in Paris?")
```

Argument names, defaults, and the docstring are auto-extracted into the
tool's `schema()`. No manual JSON schema needed.

---

## 3. Full `Tool` class

When you need full control — custom error handling, side effects,
streaming, async work — implement the protocol directly:

```python
from shipit_agent.tools.base import Tool, ToolContext, ToolOutput

class WeatherTool(Tool):
    name = "weather"
    description = "Look up current weather for a city."
    prompt_instructions = "Use this when the user asks about weather conditions."

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["city"],
                },
            },
        }

    def run(self, context: ToolContext, *, city: str, unit: str = "celsius") -> ToolOutput:
        # … call your API …
        text = f"It's 18°{unit[0].upper()} in {city}."
        return ToolOutput(text=text, metadata={"city": city, "unit": unit})

agent = Agent(llm=llm, tools=[WeatherTool(api_key="…")])
```

The `metadata` you return on `ToolOutput` is surfaced in the
`tool_completed` event payload — handy for tracing and analytics.

---

## 4. MCP server (Model Context Protocol)

MCP servers expose tools over stdio or HTTP. `shipit_agent` connects to
them with one of three transports:

```python
from shipit_agent import Agent, MCPServer
from shipit_agent.mcp import MCPSubprocessTransport, MCPHTTPTransport

# Local subprocess MCP
fs = MCPServer(
    name="filesystem",
    transport=MCPSubprocessTransport(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp/work"],
    ),
)

# Remote HTTP MCP
github = MCPServer(
    name="github",
    transport=MCPHTTPTransport(url="https://mcp.example.com/github"),
)

agent = Agent.with_builtins(llm=llm, mcps=[fs, github])
```

The runtime automatically handshakes with each MCP server, discovers
its tools, and merges them into the agent's tool registry. Failed
discoveries log a warning and continue — they don't take down the
agent.

See the [MCP guide](../guides/mcp.md) for OAuth-protected MCP servers,
persistent subprocess transports, and reconnection policies.

---

## 5. Mixing custom tools, builtins, and MCP

```python
from shipit_agent import Agent
from shipit_agent.tools import FunctionTool

def my_secret_calculator(a: int, b: int) -> int:
    """Compute a*b + 42."""
    return a * b + 42

agent = Agent.with_builtins(
    llm=llm,
    mcps=[fs, github],                                # MCP tools
    # extra_tools is forwarded to with_builtins via **kwargs:
    tools=[FunctionTool.from_callable(my_secret_calculator)],
)
```

When tool names collide, the **last** registered tool wins. The deep
agent's `merge_tools` helper enforces the same rule for `DeepAgent`.

---

## 6. Tool search — coping with 30+ tools

When the registry grows past ~10 tools, the model starts wasting tokens
just *reading* the schema list. Add `tool_search` to the prompt and
instruct the model to call it first:

```python
agent.prompt += (
    "\n\nBefore calling any other tool, first call `tool_search` to "
    "find the right one. Then proceed."
)
```

The model gets a ranked shortlist of 5 relevant tools instead of
seeing all 30. See the [Tool Search guide](../guides/tool-search.md).

---

## 7. Disabling the planner

The auto-planner runs `plan_task` once before the first LLM call. To
turn it off:

```python
from shipit_agent.policies import RouterPolicy

agent = Agent.with_builtins(llm=llm, router_policy=RouterPolicy(auto_plan=False))
```

`plan_task` is still in the registry — the model can still call it
explicitly — but the runtime won't auto-invoke it.

---

## See also

- [Custom tools guide](../guides/custom-tools.md) — protocol details
- [Tools manifest](../reference/tools.md) — every built-in tool
- [MCP guide](../guides/mcp.md) — OAuth, HTTP, and persistent transports
- [Tool search guide](../guides/tool-search.md) — scaling past 30 tools
- [Parameters Reference](../reference/parameters.md#agent)
