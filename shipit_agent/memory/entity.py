from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Entity:
    """A tracked entity (person, project, concept)."""

    name: str
    entity_type: str = "unknown"
    context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.entity_type,
            "context": self.context,
            "metadata": dict(self.metadata),
        }


class EntityMemory:
    """Track entities (people, projects, concepts) across conversations.

    Example::

        memory = EntityMemory()
        memory.add(Entity(name="Alice", entity_type="person", context="works on Project Atlas"))
        memory.add(Entity(name="Project Atlas", entity_type="project", context="Kubernetes migration"))

        entity = memory.get("Alice")
        # Entity(name="Alice", entity_type="person", context="works on Project Atlas")

        results = memory.search("Kubernetes")
        # [Entity(name="Project Atlas", ...)]
    """

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}

    def add(self, entity: Entity) -> None:
        """Add or update an entity."""
        existing = self._entities.get(entity.name)
        if existing:
            # Merge context
            if entity.context and entity.context not in existing.context:
                existing.context = (
                    f"{existing.context}; {entity.context}"
                    if existing.context
                    else entity.context
                )
            existing.metadata.update(entity.metadata)
            if entity.entity_type != "unknown":
                existing.entity_type = entity.entity_type
        else:
            self._entities[entity.name] = entity

    def get(self, name: str) -> Entity | None:
        """Get an entity by name."""
        return self._entities.get(name)

    def search(self, query: str) -> list[Entity]:
        """Search entities by keyword in name or context."""
        query_lower = query.lower()
        return [
            e
            for e in self._entities.values()
            if query_lower in e.name.lower() or query_lower in e.context.lower()
        ]

    def all(self) -> list[Entity]:
        """Return all tracked entities."""
        return list(self._entities.values())

    def remove(self, name: str) -> None:
        """Remove an entity."""
        self._entities.pop(name, None)

    def clear(self) -> None:
        self._entities.clear()
