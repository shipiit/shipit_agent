"""Triggers — an agent that reacts, and the ways that goes wrong."""

from __future__ import annotations

import threading

import pytest

from shipit_agent.triggers import (
    InMemoryTriggerQueue,
    SqliteTriggerQueue,
    Trigger,
    TriggerEvent,
    TriggerRegistry,
    fire_all,
)


class FakeAgent:
    """Records what it was asked, and can be told to fail."""

    def __init__(self, *, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self.fail = fail

    def run(self, prompt: str):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("the provider is down")
        return type("Result", (), {"output": f"handled: {prompt[:20]}"})()


@pytest.fixture
def registry():
    return TriggerRegistry(queue=InMemoryTriggerQueue())


def rsvp(event: TriggerEvent) -> str:
    return f"Log this RSVP:\n{event.data.get('body', '')}"


class TestWiring:
    def test_the_decorator_registers_it(self, registry) -> None:
        @registry.on("gmail", name="rsvp-intake")
        def handler(event):
            return "x"

        assert [t.name for t in registry.triggers()] == ["rsvp-intake"]
        assert registry.for_source("gmail")

    def test_the_function_name_is_the_default_name(self, registry) -> None:
        registry.on("gmail")(rsvp)
        assert registry.triggers()[0].name == "rsvp"

    def test_a_disabled_trigger_never_matches(self, registry) -> None:
        trigger = registry.register(
            Trigger(name="t", source="gmail", build_prompt=rsvp))
        trigger.enabled = False
        assert registry.for_source("gmail") == []


class TestFiringIsNotRunning:
    """A webhook answers in milliseconds; an agent takes seconds."""

    def test_firing_runs_nothing(self, registry) -> None:
        registry.on("gmail")(rsvp)
        agent = FakeAgent()
        registry.fire("gmail", {"body": "Jordan will attend."})
        assert agent.prompts == []
        assert registry.queue.pending() == 1

    def test_draining_runs_it(self, registry) -> None:
        registry.on("gmail")(rsvp)
        agent = FakeAgent()
        registry.fire("gmail", {"body": "Jordan will attend."})
        runs = registry.drain(agent)
        assert len(runs) == 1 and runs[0].ok
        assert "Jordan will attend." in agent.prompts[0]
        assert registry.queue.pending() == 0

    def test_an_event_fired_before_anyone_listens_is_still_there(
            self, registry) -> None:
        registry.fire("gmail", {"body": "early"})
        registry.on("gmail")(rsvp)          # wired up afterwards
        assert registry.drain(FakeAgent())[0].ok


class TestDelivery:
    def test_two_triggers_on_one_source_both_run(self, registry) -> None:
        registry.register(Trigger("a", "gmail", lambda e: "first"))
        registry.register(Trigger("b", "gmail", lambda e: "second"))
        agent = FakeAgent()
        registry.fire("gmail", {})
        runs = registry.drain(agent)
        assert sorted(run.trigger for run in runs) == ["a", "b"]
        assert agent.prompts == ["first", "second"]

    def test_returning_none_skips_without_failing(self, registry) -> None:
        """That is how a trigger filters: only RSVPs, only failures."""
        registry.register(Trigger("only-rsvp", "gmail",
                                  lambda e: None if e.data.get("kind") != "rsvp"
                                  else "handle it"))
        agent = FakeAgent()
        registry.fire("gmail", {"kind": "newsletter"})
        run = registry.drain(agent)[0]
        assert run.ok and run.skipped
        assert agent.prompts == []
        assert registry.queue.pending() == 0, "a skip still consumes the event"

    def test_an_event_nobody_listens_for_is_dropped(self, registry) -> None:
        registry.fire("stripe", {})
        assert registry.drain(FakeAgent()) == []
        assert registry.queue.pending() == 0

    def test_the_agent_is_the_callers(self, registry) -> None:
        """Nothing here builds an agent — a headless run keeps the caller's
        credentials, permissions and budget."""
        registry.on("gmail")(rsvp)
        registry.fire("gmail", {"body": "x"})
        agent = FakeAgent()
        registry.drain(agent)
        assert agent.prompts, "it ran on the agent it was handed"


class TestFailure:
    def test_a_failed_run_returns_the_event_to_the_queue(self, registry) -> None:
        registry.on("gmail")(rsvp)
        registry.fire("gmail", {"body": "x"})
        run = registry.drain(FakeAgent(fail=True))[0]
        assert not run.ok and "provider is down" in run.error
        assert registry.queue.pending() == 1, "a transient failure retries"

    def test_a_poison_event_stops_after_max_attempts(self) -> None:
        registry = TriggerRegistry(queue=InMemoryTriggerQueue(),
                                   max_attempts=2)
        registry.on("gmail")(rsvp)
        registry.fire("gmail", {"body": "x"})
        agent = FakeAgent(fail=True)
        registry.drain(agent)
        assert registry.queue.pending() == 1
        registry.drain(agent)
        assert registry.queue.pending() == 0, (
            "an event that always fails must stop, or it hides everything "
            "queued behind it")

    def test_a_handler_that_raises_is_reported_not_propagated(
            self, registry) -> None:
        def broken(event):
            raise ValueError("bad handler")

        registry.register(Trigger("broken", "gmail", broken))
        registry.fire("gmail", {})
        run = registry.drain(FakeAgent())[0]
        assert not run.ok and "bad handler" in run.error

    def test_one_failing_trigger_does_not_cancel_the_others(self, registry
                                                            ) -> None:
        registry.register(Trigger("ok", "gmail", lambda e: "fine"))
        registry.register(Trigger("bad", "gmail",
                                  lambda e: (_ for _ in ()).throw(
                                      ValueError("nope"))))
        runs = {run.trigger: run for run in
                (registry.fire("gmail", {}), registry.drain(FakeAgent()))[1]}
        assert runs["ok"].ok and not runs["bad"].ok


class TestDurability:
    def test_sqlite_survives_a_new_process(self, tmp_path) -> None:
        path = tmp_path / "triggers.db"
        first = TriggerRegistry(queue=SqliteTriggerQueue(path))
        first.fire("gmail", {"body": "3am email"})

        # A different registry over the same file — the same thing a restart
        # is. "Runs on every email" cannot mean "unless we deployed".
        second = TriggerRegistry(queue=SqliteTriggerQueue(path))
        second.on("gmail")(rsvp)
        agent = FakeAgent()
        assert second.drain(agent)[0].ok
        assert "3am email" in agent.prompts[0]

    def test_a_claimed_event_is_not_claimed_twice(self, tmp_path) -> None:
        queue = SqliteTriggerQueue(tmp_path / "t.db")
        queue.put(TriggerEvent(source="gmail"))
        assert len(queue.claim()) == 1
        assert queue.claim() == [], "a second worker must not take it too"

    def test_releasing_makes_it_available_again(self, tmp_path) -> None:
        queue = SqliteTriggerQueue(tmp_path / "t.db")
        event = TriggerEvent(source="gmail")
        queue.put(event)
        queue.claim()
        queue.release(event.id, error="boom")
        claimed = queue.claim()
        assert len(claimed) == 1 and claimed[0].attempts == 1

    def test_done_removes_it(self, tmp_path) -> None:
        queue = SqliteTriggerQueue(tmp_path / "t.db")
        event = TriggerEvent(source="gmail")
        queue.put(event)
        queue.done(event.id)
        assert queue.pending() == 0

    def test_order_is_the_order_they_arrived(self, tmp_path) -> None:
        queue = SqliteTriggerQueue(tmp_path / "t.db")
        for index in range(3):
            queue.put(TriggerEvent(source="gmail", data={"n": index},
                                   created_at=1000 + index))
        assert [e.data["n"] for e in queue.claim()] == [0, 1, 2]


class TestBatchAndReporting:
    def test_fire_all_queues_a_batch(self, registry) -> None:
        ids = fire_all(registry, "gmail", [{"n": 1}, {"n": 2}])
        assert len(set(ids)) == 2
        assert registry.queue.pending() == 2

    def test_the_summary_says_what_is_wired_and_waiting(self, registry
                                                        ) -> None:
        registry.on("gmail", description="RSVP intake")(rsvp)
        registry.fire("gmail", {})
        summary = registry.summary()
        assert summary["sources"] == ["gmail"]
        assert summary["pending"] == 1
        assert summary["triggers"][0]["description"] == "RSVP intake"


class TestWorker:
    def test_run_forever_stops_when_told(self, registry) -> None:
        registry.on("gmail")(rsvp)
        registry.fire("gmail", {"body": "x"})
        agent = FakeAgent()
        stop = threading.Event()

        worker = threading.Thread(
            target=registry.run_forever,
            kwargs={"agent": agent, "every": 0.01, "stop": stop},
            daemon=True)
        worker.start()
        for _ in range(200):                    # ≤2s, then give up
            if agent.prompts:
                break
            threading.Event().wait(0.01)
        stop.set()
        worker.join(timeout=2)
        assert agent.prompts, "the worker drained the queue"
        assert not worker.is_alive(), "and it stopped when asked"


class TestThePublicSurface:
    """A documented import that does not resolve is a broken example.

    `TriggerRegistry` was exported without `SqliteTriggerQueue`, so the
    durable setup — the one the guide leads with, and the default anybody
    running this in production wants — could not be written from the
    top-level import at all.
    """

    def test_everything_the_guides_import_is_exported(self) -> None:
        import shipit_agent

        for name in ("TriggerRegistry", "Trigger", "TriggerEvent",
                     "TriggerRun", "SqliteTriggerQueue",
                     "InMemoryTriggerQueue", "fire_all"):
            assert hasattr(shipit_agent, name), (
                f"{name} is used in the docs and not exported")

    def test_the_durable_setup_works_from_the_top_level_import(
            self, tmp_path) -> None:
        from shipit_agent import SqliteTriggerQueue, TriggerRegistry

        registry = TriggerRegistry(
            queue=SqliteTriggerQueue(tmp_path / "triggers.db"))
        registry.fire("gmail", {"body": "x"})
        assert registry.queue.pending() == 1
