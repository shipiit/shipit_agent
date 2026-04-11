from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shipit_agent.memory.conversation import ConversationMemory
from shipit_agent.memory.entity import Entity, EntityMemory
from shipit_agent.memory.semantic import (
    InMemoryVectorStore,
    SearchResult,
    SemanticMemory,
)
from shipit_agent.models import Message


@dataclass(slots=True)
class AgentMemory:
    """Unified memory system combining conversation, semantic, and entity memory.

    Example::

        # Full configuration
        memory = AgentMemory(
            conversation=ConversationMemory(strategy="summary", summary_llm=llm),
            knowledge=SemanticMemory(embedding_fn=my_embed_fn),
            entities=EntityMemory(),
        )

        # Smart defaults — one line
        memory = AgentMemory.default(llm=llm)
    """

    conversation: ConversationMemory = field(default_factory=ConversationMemory)
    knowledge: SemanticMemory = field(default_factory=lambda: SemanticMemory())
    entities: EntityMemory = field(default_factory=EntityMemory)

    @classmethod
    def default(cls, *, llm: Any = None, embedding_fn: Any = None) -> "AgentMemory":
        """Create an AgentMemory with smart defaults.

        - Conversation: summary strategy with LLM (falls back to window if no LLM)
        - Knowledge: in-memory vector store with embedding function (if provided)
        - Entities: always enabled
        """
        conv_strategy = "summary" if llm else "window"
        return cls(
            conversation=ConversationMemory(
                strategy=conv_strategy,
                summary_llm=llm,
                window_size=20,
            ),
            knowledge=SemanticMemory(
                vector_store=InMemoryVectorStore(),
                embedding_fn=embedding_fn,
            ),
            entities=EntityMemory(),
        )

    def add_message(self, message: Message) -> None:
        """Add a message to conversation memory."""
        self.conversation.add(message)

    def add_fact(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        """Add a fact to semantic knowledge memory."""
        self.knowledge.add(text, metadata)

    def add_entity(self, entity: Entity) -> None:
        """Add or update an entity."""
        self.entities.add(entity)

    def get_conversation_messages(self) -> list[Message]:
        """Get conversation messages (with strategy applied)."""
        return self.conversation.get_messages()

    def search_knowledge(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search semantic knowledge memory."""
        return self.knowledge.search(query, top_k=top_k)

    def get_entity(self, name: str) -> Entity | None:
        """Look up a tracked entity."""
        return self.entities.get(name)

    def search_entities(self, query: str) -> list[Entity]:
        """Search entities by keyword."""
        return self.entities.search(query)
