"""Regression tests for MEM-4: InMemoryVectorStore id collisions after delete.

See FINDINGS.md MEM-4. Ids were ``mem_{len(self._entries)}`` which reuse an
existing id after an interior delete, so a later delete removes two entries.
"""

from __future__ import annotations

from shipit_agent.memory.semantic import InMemoryVectorStore


class TestVectorStoreIds:
    def test_ids_never_reused_after_delete(self) -> None:
        store = InMemoryVectorStore()
        a = store.add(["a"])[0]
        b = store.add(["b"])[0]
        c = store.add(["c"])[0]
        assert len({a, b, c}) == 3

        # Delete an interior entry, then add a new one.
        store.delete([b])
        d = store.add(["d"])[0]

        ids = [e["id"] for e in store._entries]
        # No duplicate ids in the store.
        assert len(ids) == len(set(ids))
        # The new id must not collide with any surviving id.
        assert d not in {a, c}

    def test_delete_removes_only_target(self) -> None:
        store = InMemoryVectorStore()
        store.add(["a"])
        b = store.add(["b"])[0]
        store.add(["c"])
        store.delete([b])
        new_id = store.add(["d"])[0]

        # Deleting the originally-second id again must remove nothing.
        before = len(store._entries)
        store.delete([b])
        assert len(store._entries) == before

        # Deleting the new id removes exactly one entry.
        store.delete([new_id])
        assert len(store._entries) == before - 1

    def test_add_with_embeddings_shares_counter(self) -> None:
        store = InMemoryVectorStore()
        i1 = store.add(["a"])[0]
        i2 = store.add_with_embeddings(["b"], [[0.1, 0.2]])[0]
        i3 = store.add(["c"])[0]
        assert len({i1, i2, i3}) == 3
