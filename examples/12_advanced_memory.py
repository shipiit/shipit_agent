"""
12 — Advanced Memory System

Conversation memory (4 strategies), semantic search, entity tracking,
and the unified AgentMemory interface.

Run:
    python examples/12_advanced_memory.py
"""
from __future__ import annotations

import hashlib

from shipit_agent import AgentMemory, ConversationMemory, SemanticMemory, EntityMemory, InMemoryVectorStore, Entity
from shipit_agent.models import Message


def simple_embed(text: str) -> list[float]:
    """Demo embedding function using hash. Use OpenAI/sentence-transformers in production."""
    h = hashlib.sha256(text.lower().encode()).digest()
    return [float(b) / 255.0 for b in h[:16]]


def main() -> None:
    # --- Conversation Memory ---
    print("=== Conversation Memory Strategies ===\n")
    for strategy in ["buffer", "window", "token", "summary"]:
        mem = ConversationMemory(strategy=strategy, window_size=3, max_tokens=100)
        for i in range(10):
            mem.add(Message(role="user", content=f"Message about topic {i}"))
        msgs = mem.get_messages()
        print(f"  {strategy:8s}: {len(msgs):2d} messages kept (from 10)")

    # --- Semantic Memory ---
    print("\n=== Semantic Memory ===\n")
    sem = SemanticMemory(vector_store=InMemoryVectorStore(), embedding_fn=simple_embed, top_k=3)
    facts = [
        "Python was created by Guido van Rossum",
        "JavaScript runs in web browsers",
        "Rust is known for memory safety",
        "SHIPIT Agent is a powerful agent framework",
    ]
    for f in facts:
        sem.add(f)
    for query in ["Python creator", "web programming", "agent framework"]:
        results = sem.search(query)
        top = results[0] if results else None
        print(f"  '{query}' -> {top.text[:50] if top else 'no match'}")

    # --- Entity Memory ---
    print("\n=== Entity Memory ===\n")
    ent = EntityMemory()
    ent.add(Entity(name="Alice", entity_type="person", context="Lead engineer"))
    ent.add(Entity(name="Project Atlas", entity_type="project", context="K8s migration"))
    ent.add(Entity(name="Alice", context="promoted to CTO"))  # auto-merges

    alice = ent.get("Alice")
    print(f"  Alice: {alice.context}")
    print(f"  Search 'K8s': {[e.name for e in ent.search('K8s')]}")

    # --- Unified AgentMemory ---
    print("\n=== AgentMemory (Unified) ===\n")
    memory = AgentMemory.default(embedding_fn=simple_embed)
    memory.add_message(Message(role="user", content="Hello"))
    memory.add_fact("SHIPIT supports 10 LLM providers")
    memory.add_entity(Entity(name="Bob", context="new hire"))
    print(f"  Messages: {len(memory.get_conversation_messages())}")
    print(f"  Knowledge: {[r.text[:40] for r in memory.search_knowledge('LLM')]}")
    print(f"  Entity 'Bob': {memory.get_entity('Bob').context}")


if __name__ == "__main__":
    main()
