# Sessions & Memory

SHIPIT Agent has two orthogonal persistence layers:

- **Sessions** — conversation history (messages), resumable across agent runs
- **Memory** — facts extracted from tool results, queryable across sessions

Both are pluggable. In-memory implementations ship by default; file-backed implementations are available for persistence across process restarts.

## Session store

```python
from shipit_agent import Agent, FileSessionStore
from shipit_agent.llms import OpenAIChatLLM

agent = Agent(
    llm=OpenAIChatLLM(model="gpt-4o-mini"),
    session_store=FileSessionStore(root=".shipit_sessions"),
    session_id="user-42-chat-1",
)

# Turn 1
agent.run("My name is Alice.")

# Turn 2 — the agent remembers Alice because the session was saved
agent.run("What's my name?")
```

The session store persists messages after every run. On the next `run()` call with the same `session_id`, prior messages are loaded and prepended to the conversation.

### Available implementations

| Class | Storage | Use for |
|---|---|---|
| `InMemorySessionStore` | Python dict | Tests, short-lived scripts |
| `FileSessionStore` | JSON files on disk | Long-running agents, CLI tools |

### Custom store

Implement the `SessionStore` protocol:

```python
from shipit_agent.stores import SessionStore, SessionRecord

class RedisSessionStore:
    def load(self, session_id: str) -> SessionRecord | None: ...
    def save(self, record: SessionRecord) -> None: ...
```

## Memory store

Memory captures **facts** extracted from tool results. The runtime automatically adds every tool output as a `MemoryFact` after each run:

```python
from shipit_agent import Agent, FileMemoryStore

agent = Agent(
    llm=llm,
    memory_store=FileMemoryStore(root=".shipit_memory"),
)
```

### Querying memory from tools

Custom tools can read memory via `context.state["memory_store"]`:

```python
def run(self, context, **kwargs):
    memory = context.state["memory_store"]
    facts = memory.list(category="tool_result")
    # ... reason over facts
```

## Trace store

For audit logs and observability, the `TraceStore` records every `AgentEvent` with timing:

```python
from shipit_agent import Agent, FileTraceStore

agent = Agent(
    llm=llm,
    trace_store=FileTraceStore(root=".shipit_traces"),
    trace_id="run-2026-04-09-alice",
)
```

Each event is appended with `session_id`, `agent_name`, `agent_description`, and the full payload — so you can replay any agent run from disk later.

## Related

- [Architecture reference](../reference/architecture.md)
