"""Cross-runtime serialization for one durable conversation.

An agent instance lock is not sufficient: chat sessions clone agents and web
workers routinely construct a fresh agent for every request.  The durable
identity is the pair ``(session_store, session_id)``, so the lock belongs there.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterator


@dataclass(slots=True)
class _Entry:
    lock: threading.Lock
    users: int = 0


_registry_guard = threading.Lock()
_registry: dict[tuple[int, str], _Entry] = {}


def _borrow(store: Any, session_id: str) -> tuple[tuple[int, str], _Entry]:
    key = (id(store), str(session_id))
    with _registry_guard:
        entry = _registry.get(key)
        if entry is None:
            entry = _Entry(lock=threading.Lock())
            _registry[key] = entry
        entry.users += 1
    return key, entry


def _return(key: tuple[int, str], entry: _Entry) -> None:
    with _registry_guard:
        entry.users -= 1
        if entry.users == 0 and _registry.get(key) is entry:
            _registry.pop(key, None)


@contextmanager
def session_run_lock(store: Any, session_id: str) -> Iterator[None]:
    """Serialize a synchronous run with every run sharing this session."""
    key, entry = _borrow(store, session_id)
    entry.lock.acquire()
    try:
        yield
    finally:
        entry.lock.release()
        _return(key, entry)


@asynccontextmanager
async def async_session_run_lock(store: Any, session_id: str) -> AsyncIterator[None]:
    """Cancellation-safe async acquisition of the cross-runtime lock.

    Polling a non-blocking ``threading.Lock`` avoids parking the event loop and
    avoids the leaked-acquire race that ``run_in_executor(lock.acquire)`` has
    when its awaiting task is cancelled.
    """
    key, entry = _borrow(store, session_id)
    acquired = False
    try:
        while not acquired:
            acquired = entry.lock.acquire(blocking=False)
            if not acquired:
                await asyncio.sleep(0.01)
        yield
    finally:
        if acquired:
            entry.lock.release()
        _return(key, entry)
