"""Regression tests for MEM-2 / MEM-3: atomic & locked file stores.

- MEM-2: FileSessionStore.save must be atomic (temp file + os.replace), so a
  concurrent reader never sees truncated JSON.
- MEM-3: FileMemoryStore.add must be locked + atomic, so concurrent adds do
  not lose updates or corrupt the file.

See FINDINGS.md MEM-2 / MEM-3.
"""

from __future__ import annotations

import json
import threading

from shipit_agent.models import Message
from shipit_agent.stores.memory import FileMemoryStore, MemoryFact
from shipit_agent.stores.session import FileSessionStore, SessionRecord


class TestSessionStoreAtomic:
    def test_save_is_atomic_no_partial_file(self, tmp_path) -> None:
        store = FileSessionStore(tmp_path)
        rec = SessionRecord(
            session_id="s1",
            messages=[Message(role="user", content="hello")],
        )
        store.save(rec)
        path = store._path_for("s1")
        # The file must always be complete, valid JSON.
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["session_id"] == "s1"

    def test_no_temp_files_left_behind(self, tmp_path) -> None:
        store = FileSessionStore(tmp_path)
        store.save(SessionRecord(session_id="s1", messages=[]))
        leftovers = [p for p in tmp_path.iterdir() if p.suffix != ".json"]
        assert leftovers == []

    def test_concurrent_save_load_always_valid(self, tmp_path) -> None:
        store = FileSessionStore(tmp_path)
        store.save(SessionRecord(session_id="s1", messages=[]))
        errors: list[Exception] = []

        def writer() -> None:
            for i in range(50):
                store.save(
                    SessionRecord(
                        session_id="s1",
                        messages=[
                            Message(role="user", content="x" * (i % 7) * 200)
                        ],
                    )
                )

        def reader() -> None:
            for _ in range(50):
                try:
                    store.load("s1")
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestMemoryStoreAtomic:
    def test_concurrent_add_no_lost_updates(self, tmp_path) -> None:
        store = FileMemoryStore(tmp_path / "mem.json")
        n_threads = 8
        per_thread = 25

        def worker(tid: int) -> None:
            for i in range(per_thread):
                store.add(MemoryFact(content=f"fact-{tid}-{i}"))

        threads = [
            threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        facts = store._load_all()
        assert len(facts) == n_threads * per_thread

    def test_save_is_atomic_no_temp_left(self, tmp_path) -> None:
        path = tmp_path / "mem.json"
        store = FileMemoryStore(path)
        store.add(MemoryFact(content="a"))
        leftovers = [p for p in tmp_path.iterdir() if p.name != "mem.json"]
        assert leftovers == []
