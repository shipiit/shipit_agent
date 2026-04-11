---
title: Agent — Examples
description: Hands-on, copy-paste examples for building with shipit_agent.Agent.
---

# Agent — Examples

Every example below is self-contained. Swap `build_llm_from_env()` for
any LLM client you have on hand (`AnthropicChatLLM(...)`,
`OpenAIChatLLM(...)`, `BedrockChatLLM(...)`, etc.).

---

## 1. Hello world — no tools

```python
from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM

agent = Agent(llm=SimpleEchoLLM(), prompt="You are a helpful assistant.")
result = agent.run("Say hello")
print(result.output)
```

---

## 2. Hello world — with builtins

```python
from shipit_agent import Agent
from examples.run_multi_tool_agent import build_llm_from_env

llm = build_llm_from_env()
agent = Agent.with_builtins(llm=llm)

result = agent.run("Search the web for the SQLite version released in 2024.")
print(result.output)
```

`with_builtins()` ships ~30 tools out of the box including web search,
browser, code execution, and integrations.

---

## 3. Custom tool

Any object that implements `name`, `description`, `schema()`, and
`run(context, **kwargs)` is a tool. The shortest path is
`FunctionTool.from_callable`:

```python
from shipit_agent import Agent
from shipit_agent.tools import FunctionTool

def reverse_string(text: str) -> str:
    """Reverse the input string."""
    return text[::-1]

tool = FunctionTool.from_callable(reverse_string)
agent = Agent(llm=llm, tools=[tool])

result = agent.run("Reverse the string 'shipit'.")
print(result.output)
```

See the [Custom tools guide](../guides/custom-tools.md) for the full
protocol and validation patterns.

---

## 4. Multi-turn chat with session persistence

```python
from shipit_agent import Agent
from shipit_agent.stores import FileSessionStore

agent = Agent.with_builtins(
    llm=llm,
    session_store=FileSessionStore(root="~/.shipit/sessions"),
)

session = agent.chat_session(session_id="user-42")

# Turn 1
result1 = session.send("Remember that my favourite colour is teal.")
print(result1.output)

# Turn 2 — agent remembers
result2 = session.send("What's my favourite colour?")
print(result2.output)
```

See the [Sessions & Memory page](sessions.md) for a full deep-dive.

---

## 5. Streaming a research run

```python
agent = Agent.with_builtins(llm=llm)

for event in agent.stream("Find today's Bitcoin price in USD."):
    if event.type == "reasoning_started":
        print("🧠 thinking…")
    elif event.type == "reasoning_completed":
        print("🧠 thought:", event.payload.get("content", "")[:120])
    elif event.type == "tool_called":
        print("▶", event.message)
    elif event.type == "tool_completed":
        print("✓", event.message)
    elif event.type == "run_completed":
        print("answer:", event.payload.get("output", "")[:200])
```

See the [Streaming page](streaming.md) for SSE/WebSocket renderers and
full event-type tables.

---

## 6. Structured output (Pydantic)

```python
from pydantic import BaseModel
from shipit_agent import Agent

class WeatherReport(BaseModel):
    city: str
    temperature_c: float
    conditions: str

agent = Agent.with_builtins(llm=llm)
result = agent.run("What's the weather in Paris?", output_schema=WeatherReport)

print(result.parsed)            # WeatherReport(city='Paris', temperature_c=12.0, ...)
print(result.parsed.city)
```

The runtime appends a JSON-schema instruction to the user prompt and
parses the model's final answer with `PydanticParser`. Your `tools` and
`rag` continue to work normally — only the *final* answer is required
to fit the schema.

---

## 7. Agent with RAG (auto-cited answers)

```python
from shipit_agent import Agent
from shipit_agent.rag import RAG, HashingEmbedder

rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/manual.pdf")

agent = Agent.with_builtins(llm=llm, rag=rag)

result = agent.run("How do I configure logging?")
print(result.output)              # "Set SHIPIT_LOG_LEVEL=debug. [1]"

for src in result.rag_sources:
    print(f"[{src.index}] {src.source}: {src.text[:80]}")
```

The `rag=` parameter auto-wires three new tools (`rag_search`,
`rag_fetch_chunk`, `rag_list_sources`), augments the system prompt
with citation instructions, and attaches every retrieved chunk to
`result.rag_sources`. See [Agent + RAG](with-rag.md) for the full
pattern.

---

## 8. Agent with MCP server

```python
from shipit_agent import Agent, MCPServer, MCPSubprocessTransport

mcp = MCPServer(
    name="filesystem",
    transport=MCPSubprocessTransport(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp/work"],
    ),
)

agent = Agent.with_builtins(llm=llm, mcps=[mcp])

result = agent.run("List the files in /tmp/work and read the largest one.")
print(result.output)
```

See the [MCP guide](../guides/mcp.md) for HTTP transports, persistent
subprocess MCP servers, and OAuth-protected MCP endpoints.

---

## 9. Agent with hooks (audit log)

```python
from shipit_agent import Agent, AgentHooks

class AuditHooks(AgentHooks):
    def before_llm(self, messages, tool_schemas):
        print(f"[audit] sending {len(messages)} messages, {len(tool_schemas)} tools")

    def after_tool(self, tool_name, output):
        print(f"[audit] tool {tool_name} returned {len(output.text)} chars")

agent = Agent.with_builtins(llm=llm, hooks=AuditHooks())
agent.run("Search the docs and summarise.")
```

---

## 10. Agent with retry policy

```python
from shipit_agent import Agent
from shipit_agent.policies import RetryPolicy

agent = Agent.with_builtins(
    llm=llm,
    retry_policy=RetryPolicy(
        max_retries=5,
        base_delay=2.0,
        backoff_factor=2.0,
        retry_on_tool_failure=True,
    ),
)
```

---

## See also

- [Streaming](streaming.md) — render events live
- [With RAG](with-rag.md) — knowledge-grounded answers
- [With Tools](with-tools.md) — custom tools, MCP, runtime factories
- [Sessions & Memory](sessions.md) — multi-turn chat with persistence
- [Parameters Reference](../reference/parameters.md#agent)
