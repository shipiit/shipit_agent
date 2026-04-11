---
title: Agent — Memory
description: Add long-term memory to a shipit_agent.Agent — conversation summaries, semantic facts, entity tracking, and the AgentMemory unified facade.
---

# Agent — Memory

Plain `Agent.run` is stateless: it sends the prompt + the agent's
configured `history` to the LLM and returns the result. shipit_agent
ships **two complementary memory systems** that you can use
individually or together:

| System | Where it lives | Stores | How the agent uses it |
| --- | --- | --- | --- |
| **`memory_store=`** (`MemoryStore`) | passed to `Agent` | timestamped `MemoryFact` objects | The runtime's built-in `memory` tool reads/writes here. The LLM calls `memory(action="add", ...)` to remember things during a run. |
| **`AgentMemory`** | a separate Python facade you populate by hand | conversation summary + semantic facts + tracked entities | You add facts via `memory.add_fact(...)`, search with `memory.search_knowledge(...)`, and pass `history=memory.get_conversation_messages()` so the agent picks up where it left off. |

> They're **two independent stores** with different interfaces.
> `AgentMemory.knowledge` is a `SemanticMemory`, not a `MemoryStore` —
> don't try to wire it directly into `memory_store=`. Use the patterns
> below.

For session-level chat persistence within one conversation, see
[Sessions & Memory](sessions.md).

---

## 1. Quick start — `AgentMemory.default()`

`AgentMemory` bundles three memory types behind one object you call
from Python:

```python
from shipit_agent import Agent, AgentMemory

def embed(text):
    """Take a string, return a list of floats — your embedding function."""
    return my_provider.embed_one(text)

memory = AgentMemory.default(llm=llm, embedding_fn=embed)

# Pre-load whatever you know about the user. This goes into the
# semantic store and is searchable via memory.search_knowledge(...).
memory.add_fact("user_favourite_colour=teal")
memory.add_fact("user_timezone=Europe/Berlin")

# Hand the conversation history to the agent so it has prior context.
agent = Agent.with_builtins(
    llm=llm,
    history=memory.get_conversation_messages(),
)

result = agent.run("What time should I schedule the meeting?")
# Add the new turn to memory for next time.
memory.add_message(result.messages[-2])  # user
memory.add_message(result.messages[-1])  # assistant
```

`AgentMemory` is the **Python-side** memory facade. The agent doesn't
write to it automatically — you decide when to add facts and replay
the conversation. This is perfect when your application logic owns
"what to remember", as opposed to letting the LLM decide.

`AgentMemory.default(...)` returns an instance with sensible defaults:

| Component | Default | Notes |
| --- | --- | --- |
| `conversation` | `ConversationMemory(strategy="summary")` if `llm=` is set, else `"window"` | LLM-summarised rolling history |
| `knowledge` | `SemanticMemory(InMemoryVectorStore(), embedding_fn=embed)` | Vector-search over facts |
| `entities` | `EntityMemory()` | Structured `(entity, attribute, value)` triples |

You can build it explicitly if you want different strategies:

```python
from shipit_agent import (
    AgentMemory, ConversationMemory, SemanticMemory, EntityMemory,
)

memory = AgentMemory(
    conversation=ConversationMemory(strategy="window", window_size=10),
    knowledge=SemanticMemory(embedding_fn=embed),
    entities=EntityMemory(),
)
```

---

## 2. Three memory types in detail

### 2.1 `ConversationMemory` — turn history with strategies

```python
from shipit_agent import ConversationMemory
from shipit_agent.models import Message

# Buffer — keep everything (default)
mem = ConversationMemory(strategy="buffer")

# Window — keep the last N messages
mem = ConversationMemory(strategy="window", window_size=10)

# Token — keep within a token budget
mem = ConversationMemory(strategy="token", token_budget=4000)

# Summary — LLM rolls older turns into a running summary
mem = ConversationMemory(strategy="summary", summary_llm=llm)
```

Add and read messages:

```python
mem.add(Message(role="user", content="hello"))
mem.add(Message(role="assistant", content="hi back"))

for msg in mem.get_messages():
    print(msg.role, msg.content)
```

`AgentMemory.add_message(...)` and `AgentMemory.get_conversation_messages()`
forward to this layer.

### 2.2 `SemanticMemory` — vector-searchable facts

```python
from shipit_agent.memory import InMemoryVectorStore, SemanticMemory

knowledge = SemanticMemory(
    vector_store=InMemoryVectorStore(),
    embedding_fn=embed,
)

knowledge.add("user_timezone=Europe/Berlin")
knowledge.add("user prefers concise answers", metadata={"importance": "high"})
knowledge.add("project codename: panther", metadata={"project_id": 42})

hits = knowledge.search("what time zone is the user in?", top_k=3)
for hit in hits:
    print(hit.score, hit.text, hit.metadata)
```

`AgentMemory.add_fact(text, metadata=...)` is the shortcut.

### 2.3 `EntityMemory` — tracked people / projects / concepts

```python
from shipit_agent import Entity, EntityMemory

entities = EntityMemory()
entities.add(Entity(name="Alice",         entity_type="person",  context="PM on the growth team"))
entities.add(Entity(name="Project Atlas", entity_type="project", context="Kubernetes migration"))

entities.get("Alice")            # → Entity(name="Alice", entity_type="person", ...)
entities.search("Kubernetes")    # → [Entity(name="Project Atlas", ...)]
```

`Entity` fields:

| Field | Type | Description |
| --- | --- | --- |
| `name` | `str` | Identifier — also the lookup key |
| `entity_type` | `str` | `"person"`, `"project"`, `"concept"`, … (free-form, defaults to `"unknown"`) |
| `context` | `str` | Free-form description; merged on re-add |
| `metadata` | `dict[str, Any]` | Arbitrary attached data |

`AgentMemory.add_entity(entity)` and `.get_entity(name)` are the shortcuts.

---

## 3. The `Agent(memory_store=...)` low-level path

If you want the runtime's built-in `memory` tool (which the LLM can
call directly) without the `AgentMemory` facade, pass a raw
`MemoryStore`:

```python
from shipit_agent import Agent
from shipit_agent.stores import FileMemoryStore

agent = Agent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),
)

agent.run("Remember that my favourite colour is teal.")
agent.run("What's my favourite colour?")
```

The runtime registers a `memory` tool whenever `memory_store` is set,
so the LLM can read and write facts as part of its normal tool loop.
`InMemoryMemoryStore` is the test/demo backend; `FileMemoryStore`
persists across processes.

---

## 4. End-to-end: OpenAI-style "remember things across sessions"

This is the most-asked-for pattern: the agent remembers facts from
last week's conversation when the user comes back. Combine three
things:

- `session_store=FileSessionStore(...)` for the chat history
- `memory_store=FileMemoryStore(...)` so the LLM's `memory` tool can
  read/write facts during a run
- `AgentMemory` (optional) for facts your application explicitly
  curates from outside the LLM loop

```python
from shipit_agent import Agent, AgentMemory
from shipit_agent.stores import FileMemoryStore, FileSessionStore

# Application-curated facts (semantic + entities). You decide when
# to add things to this — the LLM does NOT write to it.
profile = AgentMemory.default(llm=llm, embedding_fn=embed)

agent = Agent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),         # LLM-writable
    session_store=FileSessionStore(root="~/.shipit/sessions"),     # chat history
    history=profile.get_conversation_messages(),                   # prior context
)

# --- session 1 ---
chat = agent.chat_session(session_id="user-42")
chat.send("Remember that my favourite colour is teal and I work in EU/Berlin time.")
# The LLM may also call its `memory` tool to write to FileMemoryStore.

# Mirror anything you want into the application-curated profile too.
profile.add_fact("user_favourite_colour=teal")
profile.add_fact("user_timezone=Europe/Berlin")

# --- a week later, brand-new process ---
profile = AgentMemory.default(llm=llm, embedding_fn=embed)
profile.add_fact("user_favourite_colour=teal")          # rehydrate from your DB
profile.add_fact("user_timezone=Europe/Berlin")

agent = Agent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),
    session_store=FileSessionStore(root="~/.shipit/sessions"),
    history=profile.get_conversation_messages(),
)

chat = agent.chat_session(session_id="user-42")
chat.send("Schedule a meeting next Tuesday at 10am my time.")
# The agent has the conversation history (from session_store), the
# LLM-written facts (from memory_store), and the application-curated
# profile (passed via history=).
```

Why three stores? They serve different jobs:

| Store | Owner | Stores |
| --- | --- | --- |
| `session_store` | the runtime | message log of one conversation |
| `memory_store` | the LLM's `memory` tool | timestamped `MemoryFact`s the LLM decides to remember |
| `AgentMemory` | your application code | semantic facts + entities + conversation summary you curate explicitly |

You don't need all three for every use case — pick the smallest subset
that matches what you're building. The simplest production pattern is
just `session_store` + `memory_store`.

---

## 5. Streaming events with memory writes

`memory` writes happen as tool calls, so they show up as
`tool_called` / `tool_completed` events in the stream:

```python
for event in chat.stream("Remember I'm allergic to gluten."):
    if event.type == "tool_called" and event.message == "memory":
        print("✏️ writing to memory")
    elif event.type == "tool_completed" and event.message == "memory":
        print("✓ memory updated")
    elif event.type == "run_completed":
        print(event.payload.get("output"))
```

---

## 6. Combining memory with RAG

Memory and RAG are complementary, not competitors:

| Use case | Use… |
| --- | --- |
| Remember **what the user told you** about themselves | `memory_store=` (the LLM writes via the `memory` tool) |
| **Curated facts you maintain in code** | `AgentMemory` (you call `add_fact` from outside the loop) |
| Look up **documents you indexed** (PDFs, manuals, slack messages) | `RAG` |

Plug them all in at once:

```python
from shipit_agent import Agent, AgentMemory
from shipit_agent.rag import RAG, HashingEmbedder
from shipit_agent.stores import FileMemoryStore

profile = AgentMemory.default(llm=llm, embedding_fn=embed)
rag = RAG.default(embedder=HashingEmbedder(dimension=512))
rag.index_file("docs/manual.pdf")

agent = Agent.with_builtins(
    llm=llm,
    memory_store=FileMemoryStore(root="~/.shipit/memory"),  # LLM-writable
    history=profile.get_conversation_messages(),            # curated context
    rag=rag,                                                # indexed documents
)
```

The agent now has `memory` for personal facts the LLM writes
**and** `rag_search` / `rag_fetch_chunk` for grounded answers from
indexed documents **and** prior context from your application-curated
`AgentMemory`.

---

## 7. Persisting `AgentMemory.knowledge` across processes

`AgentMemory.default(...)` uses an `InMemoryVectorStore` by default,
so facts are lost when the process restarts. Swap it for a persistent
backend:

```python
from shipit_agent import AgentMemory, SemanticMemory
from shipit_agent.memory import InMemoryVectorStore  # or your own VectorStore

# Replace with your own VectorStore implementation backed by Chroma,
# Qdrant, pgvector, sqlite, etc. — anything that satisfies the
# memory.VectorStore protocol.
class FileVectorStore:
    def __init__(self, path):
        self.path = path
        # … implement add/search/delete …

memory = AgentMemory(
    knowledge=SemanticMemory(
        vector_store=FileVectorStore("/var/data/agent.vectors"),
        embedding_fn=embed,
    ),
    # conversation + entities can stay in-memory if you don't need them persisted
)
```

The `VectorStore` protocol used by `SemanticMemory` is documented in
the [Advanced Memory guide](../guides/advanced-memory.md).

---

## 8. Inspect what's in memory

```python
# Conversation
for msg in memory.get_conversation_messages():
    print(msg.role, msg.content[:80])

# Semantic facts
for hit in memory.search_knowledge("colour", top_k=5):
    print(hit.score, hit.text)

# Entities
print(memory.get_entity("Alice"))
for entity in memory.search_entities("growth"):
    print(entity.name, entity.entity_type, entity.context)
```

---

## See also

- [Sessions & Memory](sessions.md) — multi-turn chat persistence
- [Advanced Memory guide](../guides/advanced-memory.md) — every memory
  strategy with worked examples
- [DeepAgent → Memory](../deep-agents/deep-agent.md#memory)
- [Parameters Reference → Agent](../reference/parameters.md#agent)
- [Examples](examples.md) — copy-paste recipes
- Notebook: `notebooks/26_agent_memory.ipynb` — every example on this
  page as a runnable notebook
