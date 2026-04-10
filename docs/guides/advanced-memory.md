# Advanced Memory System

Three types of memory working together: **conversation** (what was said), **semantic** (what was learned), and **entity** (who/what is involved). Use `AgentMemory.default()` for zero-config smart defaults.

---

## Quick Start — One Line

```python
from shipit_agent import AgentMemory

memory = AgentMemory.default(llm=llm, embedding_fn=my_embed_fn)
# Gets: summary conversation memory + semantic search + entity tracking
```

---

## Conversation Memory

Four strategies for managing conversation history. Each controls how old messages are handled as conversations grow.

```python
from shipit_agent import ConversationMemory
from shipit_agent.models import Message

# --- Buffer: keep everything (default) ---
mem = ConversationMemory(strategy="buffer")
for i in range(100):
    mem.add(Message(role="user", content=f"Message {i}"))
print(len(mem.get_messages()))  # 100

# --- Window: keep last N messages ---
mem = ConversationMemory(strategy="window", window_size=10)
for i in range(100):
    mem.add(Message(role="user", content=f"Message {i}"))
msgs = mem.get_messages()
print(len(msgs))           # 10
print(msgs[0].content)     # "Message 90"

# --- Token: keep within token budget ---
mem = ConversationMemory(strategy="token", max_tokens=500)
mem.add(Message(role="user", content="x" * 2000))  # big message
mem.add(Message(role="user", content="small"))       # small message
msgs = mem.get_messages()
print(len(msgs))  # 1 (only "small" fits in budget)

# --- Summary: LLM summarizes old messages ---
mem = ConversationMemory(strategy="summary", summary_llm=llm, window_size=5)
for i in range(20):
    mem.add(Message(role="user", content=f"Question about topic {i}"))
    mem.add(Message(role="assistant", content=f"Answer about topic {i}"))
msgs = mem.get_messages()
print(len(msgs))                          # 6 (1 summary + 5 recent)
print(msgs[0].content[:50])               # "Previous conversation summary: ..."
print(msgs[0].metadata.get("summary"))    # True
```

| Strategy | Behavior | Best for |
|---|---|---|
| `buffer` | Keep all messages | Short conversations |
| `window` | Keep last N messages | Chatbots |
| `summary` | Summarize old with LLM | Long conversations |
| `token` | Keep within N tokens | Token-budget apps |

---

## Semantic Memory — Search by Meaning

Embedding-based fact storage and retrieval. Find facts by meaning, not keywords.

```python
from shipit_agent import SemanticMemory, InMemoryVectorStore

# Your embedding function (OpenAI, sentence-transformers, etc.)
def my_embed(text: str) -> list[float]:
    # Example: use OpenAI embeddings
    # response = openai.embeddings.create(input=text, model="text-embedding-3-small")
    # return response.data[0].embedding
    import hashlib
    h = hashlib.sha256(text.lower().encode()).digest()
    return [float(b) / 255.0 for b in h[:16]]

memory = SemanticMemory(
    vector_store=InMemoryVectorStore(),
    embedding_fn=my_embed,
    top_k=3,
)

# Store facts
memory.add("Python was created by Guido van Rossum in 1991")
memory.add("JavaScript was created for Netscape Navigator in 1995")
memory.add("Rust focuses on memory safety without garbage collection")
memory.add("SHIPIT Agent supports 10 LLM providers")
memory.add("FastAPI uses Python type hints for validation")

# Search by meaning
results = memory.search("Who created Python?")
for r in results:
    print(f"  [{r.score:.3f}] {r.text}")

# Bulk add
ids = memory.add_many([
    "Docker uses containerization",
    "Kubernetes orchestrates containers",
])
```

### Custom vector stores

Implement the `VectorStore` protocol to plug in any backend:

```python
from shipit_agent import VectorStore

class MyChromaStore:
    """Example: ChromaDB backend."""
    def add(self, texts, metadatas=None):
        # self.collection.add(documents=texts, ...)
        ...
    def add_with_embeddings(self, texts, embeddings, metadatas=None):
        # self.collection.add(documents=texts, embeddings=embeddings, ...)
        ...
    def search(self, query_embedding, top_k=5):
        # results = self.collection.query(query_embeddings=[query_embedding], ...)
        ...
    def delete(self, ids):
        # self.collection.delete(ids=ids)
        ...
```

---

## Entity Memory — Track People, Projects, Concepts

```python
from shipit_agent import EntityMemory, Entity

mem = EntityMemory()

# Add entities
mem.add(Entity(name="Alice", entity_type="person", context="Lead engineer on Project Atlas"))
mem.add(Entity(name="Bob", entity_type="person", context="Data scientist, ML team"))
mem.add(Entity(name="Project Atlas", entity_type="project", context="Kubernetes migration, due Q2 2026"))

# Lookup
alice = mem.get("Alice")
print(f"{alice.name}: {alice.entity_type} — {alice.context}")
# Alice: person — Lead engineer on Project Atlas

# Search by keyword
results = mem.search("Kubernetes")
for e in results:
    print(f"  {e.name} ({e.entity_type}): {e.context}")

# Updates merge automatically
mem.add(Entity(name="Alice", context="promoted to CTO"))
alice = mem.get("Alice")
print(alice.context)  # "Lead engineer on Project Atlas; promoted to CTO"

# List all
print([e.name for e in mem.all()])  # ["Alice", "Bob", "Project Atlas"]

# Remove
mem.remove("Bob")
print(mem.get("Bob"))  # None
```

---

## AgentMemory — Unified Interface

Combine all three memory types into one system:

```python
from shipit_agent import AgentMemory, ConversationMemory, SemanticMemory, EntityMemory, Entity
from shipit_agent.models import Message

# Full configuration
memory = AgentMemory(
    conversation=ConversationMemory(strategy="summary", summary_llm=llm, window_size=20),
    knowledge=SemanticMemory(embedding_fn=my_embed, top_k=5),
    entities=EntityMemory(),
)

# Or use smart defaults
memory = AgentMemory.default(llm=llm, embedding_fn=my_embed)

# Unified API
memory.add_message(Message(role="user", content="I work with Alice on Project Atlas"))
memory.add_fact("SHIPIT Agent supports parallel tool execution")
memory.add_entity(Entity(name="Alice", entity_type="person", context="teammate"))

# Query each system
msgs = memory.get_conversation_messages()
facts = memory.search_knowledge("parallel execution")
alice = memory.get_entity("Alice")
people = memory.search_entities("Alice")
```
