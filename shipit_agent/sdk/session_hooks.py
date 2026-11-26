"""SessionStart and SessionEnd: the two hook events that fire around a session, not inside a run.

``query()`` is one session; an ``AgentClient`` is one from ``connect`` to
``disconnect``. ``SessionStart`` gets ``source`` (``startup`` or ``resume``,
which a matcher can select) and may return ``additionalContext`` for the
first prompt; ``SessionEnd`` gets ``reason``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .hooks import SESSION_EVENTS, HookMatcher, _caller, _context
from .tools import HOME_LOOP

__all__ = ["SESSION_EVENTS", "SessionHooks", "with_context"]


class SessionHooks:
    """The session-level callbacks of one agent."""

    def __init__(self, spec: Any, *, base: dict[str, Any], log: Any = None) -> None:
        matchers: dict[str, list[HookMatcher]] = {
            event: list(spec.get(event) or []) for event in SESSION_EVENTS
        } if isinstance(spec, dict) else {}
        self._calls = {event: [_caller(event, matcher, base, log) for matcher in found]
                       for event, found in matchers.items()}
        self._ended = False

    async def start(self, *, resumed: bool) -> str:
        """Run SessionStart; the context its hooks want added to the first prompt."""
        source = "resume" if resumed else "startup"
        outputs = await self._fire("SessionStart", source, {"source": source})
        return "\n\n".join(text for output in outputs if (text := _context(output)))

    async def end(self, reason: str = "other") -> None:
        """Run SessionEnd, once."""
        if not self._ended:
            self._ended = True
            await self._fire("SessionEnd", reason, {"reason": reason})

    async def _fire(self, event: str, subject: str, data: dict[str, Any]) -> list[Any]:
        calls = self._calls.get(event) or []
        if not calls:
            return []
        loop = asyncio.get_running_loop()

        def run() -> list[Any]:
            # Off the caller's loop, as hooks inside a run are, so an async
            # callback may await work that loop does.
            HOME_LOOP.set(loop)
            return [output for call in calls for output in call(subject, data)]

        return await asyncio.to_thread(run)


def with_context(prompt: str, context: str) -> str:
    """*prompt* with SessionStart's additions after it, as UserPromptSubmit's are."""
    return f"{prompt}\n\n{context}" if context else prompt
