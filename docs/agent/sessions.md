---
title: Agent — Sessions & Memory
description: Multi-turn chat with persistent sessions, conversation forking, and long-term memory for shipit_agent.Agent.
---

# Agent — Sessions & Memory

Plain `Agent.run` is stateless: it sends the prompt + the agent's
configured `history` to the LLM and returns the result. To build a
**chat experience** that remembers earlier turns, you have two
orthogonal building blocks:

| Building block | Lives at | Lifetime | Use it for |
| --- | --- | --- | --- |
| **Session** | `SessionStore` | one conversation | Multi-turn chat history (user/assistant messages) |
| **Memory** | `MemoryStore` | across conversations | Long-term facts the agent should remember |

The two compose: a long-running chat is a session that also writes to
memory.

---

## 1. Multi-turn chat with `chat_session()`

`agent.chat_session(session_id=...)` returns an `AgentChatSession`
bound to a specific session id. Each `send()` / `stream()` call appends
to that session's history.

```python
from shipit_agent import Agent
from shipit_agent.stores import InMemorySessionStore

agent = Agent.with_builtins(
    llm=llm,
    session_store=InMemorySessionStore(),
)

session = agent.chat_session(session_id="user-42")

session.send("Remember that I work in EU/Berlin time.")
session.send("Schedule a 30-minute meeting next Tuesday at 10am my time.")
# The agent has both turns in context — it knows "my time" means EU/Berlin.
```

`session.history()` returns the full message list at any point.

---

## 2. Persistent sessions across restarts

Swap `InMemorySessionStore` for `FileSessionStore` and your sessions
survive process restarts:

```python
from shipit_agent.stores import FileSessionStore

agent = Agent.with_builtins(
    llm=llm,
    session_store=FileSessionStore(root="~/.shipit/sessions"),
)
session = agent.chat_session(session_id="user-42")
```

Each session is one JSON file under `~/.shipit/sessions/`. The store
implements the simple `SessionStore` protocol — implement your own to
back sessions on Postgres, Redis, DynamoDB, etc.

---

## 3. Streaming inside a session

```python
for event in session.stream("What did I ask earlier?"):
    print(f"[{event.type}] {event.message}")
```

Identical to `agent.stream(...)` — every event flows through, the only
extra step is that the new turn is also persisted to the session store.

---

## 4. Conversation forking and resuming

`SessionManager` (in `shipit_agent.session_manager`) layers
fork/archive/resume on top of any `SessionStore`:

```python
from shipit_agent import SessionManager
from shipit_agent.stores import FileSessionStore

manager = SessionManager(store=FileSessionStore(root="~/.shipit/sessions"))

# Create a fresh session
session_id = manager.create()

# Fork from an existing session at the third message
fork_id = manager.fork(parent_id=session_id, from_message=3)

# Archive a session (soft-delete)
manager.archive(session_id)

# List all live sessions
for record in manager.list_sessions():
    print(record.session_id, len(record.messages))
```

Forking is great for "what if" branches: a user's main thread plus
half a dozen exploratory branches that all share the first few
messages.

---

## 5. Long-term memory

`AgentMemory` is a unified facade over three memory types:

| Memory type | Stores | Retrieves by |
| --- | --- | --- |
| `ConversationMemory` | turn history with strategies (buffer / window / token / summary) | recency |
| `SemanticMemory` | embedded facts | vector similarity |
| `EntityMemory` | structured `(entity, attribute, value)` triples | entity name |

```python
from shipit_agent import Agent, AgentMemory

memory = AgentMemory.default(llm=llm, embedding_fn=my_embed_fn)

agent = Agent.with_builtins(
    llm=llm,
    memory_store=memory.knowledge,        # backs the runtime's memory tool
)

# Run 1
agent.run("My favourite colour is teal.")
memory.add_fact("user_favourite_colour=teal")

# Run 2 — same agent, fresh prompt; memory is still there
agent.run("What's my favourite colour?")
```

See the [Advanced memory guide](../guides/advanced-memory.md) for the
full set of strategies, retrieval knobs, and persistence backends.

---

## 6. Combining sessions + memory

The pattern most production chat features use:

```python
from shipit_agent import Agent, AgentMemory
from shipit_agent.stores import FileSessionStore

memory = AgentMemory.default(llm=llm, embedding_fn=my_embed_fn)

agent = Agent.with_builtins(
    llm=llm,
    session_store=FileSessionStore(root="~/.shipit/sessions"),
    memory_store=memory.knowledge,
)

session = agent.chat_session(session_id="user-42")
session.send("Remember that I prefer concise answers.")
# session_store has the message history; memory_store has the fact.

# A week later, in a different process:
session = agent.chat_session(session_id="user-42")
session.send("Tell me about Python's GIL.")
# The agent has both: the conversation history AND the long-term fact.
```

---

## 7. Hooks for observability

Subscribe to events as they happen via `add_event_callback` or
`add_packet_callback`:

```python
def on_event(event):
    print(f"[{event.type}] {event.message}")

session.add_event_callback(on_event)

for _ in session.stream("Search the docs"):
    pass
```

For a JSON-friendly callback (useful for logging and analytics) use
`add_packet_callback` — packets are SSE/WebSocket-shaped dicts.

---

## See also

- [Sessions guide](../guides/sessions.md) — sessionstore protocol details
- [Advanced memory guide](../guides/advanced-memory.md) — every memory
  strategy with examples
- [`SessionManager` API](../reference/parameters.md#agentchatsession-agentchat_session-deepagentchat)
- [Examples](examples.md#4-multi-turn-chat-with-session-persistence)
