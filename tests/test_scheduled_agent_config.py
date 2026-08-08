from __future__ import annotations

import argparse
import sqlite3

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.schedule import (
    AgentScheduler,
    ScheduledAgentConfig,
    ScheduledJob,
    SQLiteJobStore,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Agent:
    def __init__(self, label: str, *, error: Exception | None = None) -> None:
        self.label = label
        self.error = error
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return type(
            "Result",
            (),
            {
                "metadata": {},
                "events": [
                    type(
                        "Event",
                        (),
                        {
                            "type": "run_completed",
                            "payload": {
                                "usage": {
                                    "prompt_tokens": 20,
                                    "completion_tokens": 5,
                                    "cache_read_input_tokens": 10,
                                }
                            },
                        },
                    )()
                ],
            },
        )()


def test_config_round_trip_and_validation() -> None:
    config = ScheduledAgentConfig(
        provider="anthropic",
        model="claude-sonnet",
        role="researcher",
        project_root="/repo",
        runtime="role",
        optimized=True,
        permission_mode="plan",
        guardrails="strict",
        mcps=["github", "sentry"],
        connections=["slack"],
        skills=["release-audit"],
        auto_use_skills=False,
        max_iterations=12,
        stream_events=True,
        metadata={"team": "platform"},
    )

    assert ScheduledAgentConfig.from_dict(config.to_dict()) == config
    with pytest.raises(ValueError, match="runtime"):
        ScheduledAgentConfig(runtime="container").validate()
    with pytest.raises(ValueError, match="role runtime"):
        ScheduledAgentConfig(runtime="role").validate()


def test_store_persists_complete_agent_configuration_and_status(tmp_path) -> None:
    store = SQLiteJobStore(str(tmp_path / "jobs.db"))
    config = ScheduledAgentConfig(
        provider="openai",
        model="gpt-test",
        project_root="/repo",
        mcps=["github"],
        connections=["slack"],
    )
    store.save(
        ScheduledJob(
            name="audit",
            prompt="audit repo",
            session_id="daily",
            agent_config=config,
            next_run=123.0,
            enabled=False,
            consecutive_failures=2,
            last_error="rate limited",
            last_run=100.0,
        )
    )

    loaded = store.load("audit")
    assert loaded is not None
    assert loaded.agent_config == config
    assert loaded.enabled is False
    assert loaded.consecutive_failures == 2
    assert loaded.last_error == "rate limited"
    assert loaded.last_run == 100.0
    store.close()


def test_store_migrates_a_legacy_database(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE jobs (
            name TEXT PRIMARY KEY, prompt TEXT NOT NULL,
            interval_seconds REAL, at TEXT, cron TEXT, session_id TEXT,
            max_runs INTEGER, runs INTEGER NOT NULL DEFAULT 0,
            next_run REAL NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        "INSERT INTO jobs (name, prompt, runs, next_run) VALUES ('old', 'run', 1, 9)"
    )
    connection.commit()
    connection.close()

    store = SQLiteJobStore(str(path))
    loaded = store.load("old")
    assert loaded is not None
    assert loaded.agent_config == ScheduledAgentConfig()
    assert loaded.enabled is True
    store.close()


def test_resolver_selects_a_different_agent_for_each_job() -> None:
    clock = _Clock()
    agents: dict[str, _Agent] = {}

    def resolve(config: ScheduledAgentConfig) -> _Agent:
        key = f"{config.provider}:{config.model}"
        return agents.setdefault(key, _Agent(key))

    scheduler = AgentScheduler(
        agent_resolver=resolve, clock=clock, sleep=lambda _seconds: None
    )
    scheduler.add(
        "fast report",
        every=10,
        name="fast",
        agent_config={"provider": "openai", "model": "small"},
    )
    scheduler.add(
        "deep audit",
        every=10,
        name="deep",
        agent_config={"provider": "anthropic", "model": "large"},
    )

    clock.advance(10)
    results = scheduler.run_pending()

    assert agents["openai:small"].prompts == ["fast report"]
    assert agents["anthropic:large"].prompts == ["deep audit"]
    assert [result.schedule_metadata["job_name"] for result in results] == [
        "fast",
        "deep",
    ]
    assert all(result.schedule_metadata["token_count"] == 25 for result in results)


def test_failure_is_isolated_and_pause_resume_is_persisted(tmp_path) -> None:
    clock = _Clock()
    errors: list[str] = []
    healthy = _Agent("healthy")

    def resolve(config: ScheduledAgentConfig) -> _Agent:
        if config.provider == "broken":
            return _Agent("broken", error=RuntimeError("provider unavailable"))
        return healthy

    store = SQLiteJobStore(str(tmp_path / "jobs.db"))
    scheduler = AgentScheduler(
        agent_resolver=resolve,
        clock=clock,
        sleep=lambda _seconds: None,
        store=store,
    )
    broken = scheduler.add(
        "bad",
        every=5,
        name="broken",
        agent_config={"provider": "broken"},
        on_error=lambda error: errors.append(str(error)),
    )
    healthy_job = scheduler.add("good", every=5, name="healthy")
    scheduler.set_enabled("healthy", False)
    clock.advance(5)

    assert scheduler.run_pending() == []
    assert broken.consecutive_failures == 1
    assert broken.last_error == "provider unavailable"
    assert errors == ["provider unavailable"]
    assert healthy.prompts == []

    scheduler.set_enabled("healthy", True)
    clock.advance(5)
    fired = scheduler.run_pending()
    assert len(fired) == 1
    assert healthy.prompts == ["good"]
    assert healthy_job.runs == 1
    assert store.load("healthy").enabled is True
    store.close()


def test_overdue_paused_job_stays_paused_after_restart(tmp_path) -> None:
    clock = _Clock()
    store = SQLiteJobStore(str(tmp_path / "jobs.db"))
    store.save(
        ScheduledJob(
            name="paused",
            prompt="do not run",
            interval_seconds=5,
            next_run=clock.now - 10,
            enabled=False,
            runs=3,
        )
    )
    agent = _Agent("unused")
    scheduler = AgentScheduler(
        agent, clock=clock, sleep=lambda _seconds: None, store=store
    )

    restored = scheduler.add("do not run", every=5, name="paused")

    assert restored.enabled is False
    assert restored.runs == 3
    assert restored.next_run == clock.now - 10
    assert scheduler.run_pending() == []
    assert agent.prompts == []
    store.close()


def test_streaming_job_forwards_live_events_and_returns_result() -> None:
    clock = _Clock()
    events = [
        AgentEvent(type="run_started", message="started"),
        AgentEvent(type="text_delta", message="answer", payload={"delta": "ok"}),
        AgentEvent(
            type="run_completed",
            message="complete",
            payload={
                "output": "ok",
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        ),
    ]

    class StreamingAgent:
        def stream(self, _prompt: str):
            yield from events

    received: list[tuple[str, str]] = []
    scheduler = AgentScheduler(
        StreamingAgent(),
        clock=clock,
        sleep=lambda _seconds: None,
        on_event=lambda job, event: received.append((job.name, event.type)),
    )
    scheduler.add(
        "stream this",
        every=5,
        name="live",
        agent_config={"stream_events": True},
    )
    clock.advance(5)

    fired = scheduler.run_pending()

    assert received == [("live", event.type) for event in events]
    assert fired[0].agent_result.output == "ok"
    assert fired[0].schedule_metadata["token_count"] == 6
    assert fired[0].schedule_metadata["streamed"] is True


def test_cli_resolver_builds_job_specific_role_with_capabilities(monkeypatch) -> None:
    import shipit_agent
    from shipit_agent.cli.commands.jobs import build_scheduled_agent

    attached: list[str] = []
    monkeypatch.setattr(
        shipit_agent,
        "connect_mcp",
        lambda name: (
            attached.append(name) or type("MCP", (), {"name": name, "tools": []})()
        ),
    )
    config = ScheduledAgentConfig(
        provider="echo",
        role="researcher",
        runtime="role",
        project_root="/tmp",
        mcps=["github"],
        connections=["slack"],
        skills=["code-workflow-assistant"],
        auto_use_skills=False,
        max_iterations=11,
    )

    agent = build_scheduled_agent(config, argparse.Namespace())

    assert attached == ["github"]
    assert agent.name == "researcher"
    assert str(agent.project_root) == "/tmp"
    assert agent.max_iterations == 11
    assert agent.default_skill_ids == ["code-workflow-assistant"]
    assert agent.auto_use_skills is False
    assert agent.metadata["scheduled"] is True
    assert agent.metadata["required_connections"] == ["slack"]


def test_a_permanently_broken_job_is_paused_rather_than_retried_forever():
    """A job whose provider is gone fails identically every interval.

    Counting that and doing nothing means it runs for as long as the
    daemon lives, burning quota and filling the log with one line.
    """
    from shipit_agent.schedule import AgentScheduler

    clock = {"now": 0.0}
    scheduler = AgentScheduler(
        agent=_ExplodingAgent(), clock=lambda: clock["now"],
        max_consecutive_failures=3)
    scheduler.add("do the thing", every=60, name="broken")

    for _ in range(3):
        clock["now"] += 61
        scheduler.run_pending()

    job = scheduler.jobs[0]
    assert job.enabled is False
    assert job.consecutive_failures == 3

    # Paused, not deleted: the configuration survives.
    clock["now"] += 61
    scheduler.run_pending()
    assert job.consecutive_failures == 3, "a paused job does not keep trying"


def test_resuming_a_fixed_job_clears_the_history_that_paused_it():
    """Otherwise the very next failure pauses it again, on a count that
    belonged to the problem somebody just fixed."""
    from shipit_agent.schedule import AgentScheduler

    scheduler = AgentScheduler(agent=_ExplodingAgent(),
                               max_consecutive_failures=2)
    job = scheduler.add("do the thing", every=60, name="broken")
    job.consecutive_failures = 2
    job.enabled = False

    scheduler.set_enabled("broken", True)
    assert job.consecutive_failures == 0 and job.last_error == ""


def test_the_behaviour_can_be_switched_off():
    """A caller who would rather watch it fail is entitled to."""
    from shipit_agent.schedule import AgentScheduler

    clock = {"now": 0.0}
    scheduler = AgentScheduler(agent=_ExplodingAgent(),
                               clock=lambda: clock["now"],
                               max_consecutive_failures=0)
    scheduler.add("do the thing", every=60, name="broken")
    for _ in range(6):
        clock["now"] += 61
        scheduler.run_pending()
    assert scheduler.jobs[0].enabled is True


class _ExplodingAgent:
    def run(self, prompt, **kwargs):
        raise RuntimeError("the provider is gone")

    def stream(self, prompt, **kwargs):
        raise RuntimeError("the provider is gone")
