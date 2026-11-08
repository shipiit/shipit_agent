"""Triggers — an agent that reacts, not only one you ask.

Everything else in this library starts with a person typing. A trigger starts
with the *world*: an email arrives, a row lands, a webhook fires, a schedule
comes round, and the agent runs without anyone watching.

    triggers = TriggerRegistry(queue=SqliteTriggerQueue("triggers.db"))

    @triggers.on("gmail", name="rsvp-intake")
    def rsvp(event: TriggerEvent) -> str:
        return f"Log this RSVP in guests.csv:\\n\\n{event.data['body']}"

    triggers.fire("gmail", {"body": "Jordan Lee will attend."})
    triggers.drain(agent)      # → runs the agent on each queued event

Four decisions, each of which is the difference between this being useful and
being a footgun:

**Firing and running are separate.** `fire()` only records. `drain()` runs.
A webhook handler must return in milliseconds, and an agent takes seconds —
coupling them means the sender times out and retries, and the agent runs
twice on the same email.

**The queue is durable by default.** An event that arrives while nothing is
draining must still be there afterwards, or "runs on every email" is a claim
that quietly fails at 3am. :class:`SqliteTriggerQueue` is the default;
:class:`InMemoryTriggerQueue` exists for tests and says so.

**Every event is delivered once.** A run that crashes leaves its event
*claimed*, not lost — it is released back after a visibility timeout, so a
transient failure retries and a poison event stops after `max_attempts`
rather than looping forever.

**A trigger builds a prompt; it does not build an agent.** The handler
returns text (or `None` to skip), and the caller supplies the agent. That
keeps the credentials, the permission engine and the budget in the caller's
hands, where a headless run needs them most.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

from .queues import VISIBILITY_SECONDS as VISIBILITY_SECONDS
from .queues import InMemoryTriggerQueue, SqliteTriggerQueue, TriggerQueue
from .trigger_types import Trigger, TriggerEvent, TriggerRun

__all__ = [
    "InMemoryTriggerQueue",
    "SqliteTriggerQueue",
    "Trigger",
    "TriggerEvent",
    "TriggerQueue",
    "TriggerRegistry",
    "TriggerRun",
]


class TriggerRegistry:
    """What is wired to what, and the loop that delivers it."""

    def __init__(
        self,
        queue: TriggerQueue | None = None,
        *,
        max_attempts: int = 3,
    ) -> None:
        self.queue = queue if queue is not None else SqliteTriggerQueue()
        self.max_attempts = max_attempts
        self._triggers: dict[str, Trigger] = {}

    # ── wiring ───────────────────────────────────────────────────────────

    def register(self, trigger: Trigger) -> Trigger:
        self._triggers[trigger.name] = trigger
        return trigger

    def on(self, source: str, *, name: str | None = None,
           description: str = "") -> Callable[[Callable], Callable]:
        """Decorator form::

            @triggers.on("gmail", name="rsvp-intake")
            def rsvp(event):
                return f"Log this RSVP:\\n{event.data['body']}"
        """

        def decorate(handler: Callable[[TriggerEvent], str | None]):
            self.register(Trigger(
                name=name or handler.__name__, source=source,
                build_prompt=handler, description=description or
                (handler.__doc__ or "").strip()))
            return handler

        return decorate

    def triggers(self) -> list[Trigger]:
        return list(self._triggers.values())

    def for_source(self, source: str) -> list[Trigger]:
        return [t for t in self._triggers.values()
                if t.source == source and t.enabled]

    # ── receiving ────────────────────────────────────────────────────────

    def fire(self, source: str, data: dict[str, Any] | None = None) -> str:
        """Record that something happened. Returns the event id.

        Deliberately does not run anything: a webhook must answer in
        milliseconds, and an agent takes seconds. Coupling them is how the
        sender times out and delivers the same email twice.
        """
        event = TriggerEvent(source=source, data=dict(data or {}))
        self.queue.put(event)
        return event.id

    # ── running ──────────────────────────────────────────────────────────

    def drain(self, agent: Any, *, limit: int = 10,
              on_run: Callable[[TriggerRun], None] | None = None
              ) -> list[TriggerRun]:
        """Run the agent once per queued event, for every matching trigger.

        The agent is supplied by the caller, so a headless run keeps the same
        credentials, permissions and budget as an interactive one. Nothing
        here builds an agent, and nothing here widens what one may do.
        """
        runs: list[TriggerRun] = []
        for event in self.queue.claim(limit=limit):
            matched = self.for_source(event.source)
            if not matched:
                # Nothing is listening for this source. Dropping it keeps a
                # queue from filling with events nobody wants; the count is
                # visible through `pending()` before it happens.
                self.queue.done(event.id)
                continue

            failed = False
            for trigger in matched:
                run = self._run_one(agent, trigger, event)
                runs.append(run)
                if on_run is not None:
                    on_run(run)
                failed = failed or (not run.ok and not run.skipped)

            if not failed:
                self.queue.done(event.id)
            elif event.attempts + 1 >= self.max_attempts:
                # A poison event must stop, or it retries until the end of
                # time and hides everything behind it.
                self.queue.done(event.id)
            else:
                self.queue.release(event.id, error=runs[-1].error)
        return runs

    def _run_one(self, agent: Any, trigger: Trigger,
                 event: TriggerEvent) -> TriggerRun:
        try:
            prompt = trigger.prompt_for(event)
        except Exception as exc:                          # noqa: BLE001
            return TriggerRun(trigger=trigger.name, event_id=event.id,
                              ok=False, error=f"building the prompt: {exc}")
        if prompt is None:
            # The handler read the event and decided it was not for it. Not
            # a failure — it is how a trigger filters.
            return TriggerRun(trigger=trigger.name, event_id=event.id,
                              ok=True, skipped=True)
        try:
            result = agent.run(prompt)
        except Exception as exc:                          # noqa: BLE001
            return TriggerRun(trigger=trigger.name, event_id=event.id,
                              ok=False, error=str(exc)[:500])
        return TriggerRun(trigger=trigger.name, event_id=event.id, ok=True,
                          output=str(getattr(result, "output", result) or ""))

    def run_forever(self, agent: Any, *, every: float = 5.0,
                    stop: threading.Event | None = None,
                    on_run: Callable[[TriggerRun], None] | None = None) -> None:
        """Drain in a loop until `stop` is set.

        The simplest possible worker: for anything bigger, call `drain()`
        from your own scheduler, which is what a production deployment
        already has.
        """
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                self.drain(agent, on_run=on_run)
            except Exception:                             # noqa: BLE001
                # A worker that dies on one bad drain stops reacting to
                # everything. The event itself is already released.
                pass
            stop.wait(every)

    # ── reporting ────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        return {
            "triggers": [
                {"name": t.name, "source": t.source, "enabled": t.enabled,
                 "description": t.description}
                for t in self._triggers.values()
            ],
            "sources": sorted({t.source for t in self._triggers.values()}),
            "pending": self.queue.pending(),
        }


def fire_all(registry: TriggerRegistry, source: str,
             events: Iterable[dict[str, Any]]) -> list[str]:
    """Queue a batch — one poll of an inbox, one page of rows."""
    return [registry.fire(source, data) for data in events]
