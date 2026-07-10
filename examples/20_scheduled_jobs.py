"""
20 — Scheduled jobs: cron for agents (`AgentScheduler`).

Register prompts to run on a schedule and fire them when due:

    • every N seconds        sched.add("...", every=3600)
    • daily at a wall time   sched.add("...", at="09:00")
    • cron expression        sched.add("...", cron="0 9 * * 1-5")   # needs croniter

`run_forever()` blocks and fires jobs as they come due. For a *deterministic*
demo (and for unit tests) you can inject a fake clock so schedules fire with no
real waiting — that's what this example does.

Note: the scheduler runs **in-process** — jobs live as long as your process
does. For durable, set-and-forget scheduling, drive `run_pending()` from OS
cron / systemd, or persist state from an `on_result` hook.

Run:
    python examples/20_scheduled_jobs.py
"""

from __future__ import annotations

from shipit_agent import Agent, AgentScheduler
from shipit_agent.llms.base import LLMResponse


class LocalLLM:
    """A tiny offline LLM so the example runs with no API key."""

    def complete(self, *, messages, **_kwargs) -> LLMResponse:
        user = next(
            (m for m in reversed(messages) if _role(m) == "user"), None
        )
        text = _content(user) if user else ""
        return LLMResponse(content=f"[done] {text[:60]}")


def _role(m):
    return m.get("role") if isinstance(m, dict) else getattr(m, "role", "")


def _content(m):
    return m.get("content") if isinstance(m, dict) else getattr(m, "content", "")


class Clock:
    """A controllable clock so we can watch a day pass in milliseconds."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def main() -> None:
    agent = Agent(llm=LocalLLM(), auto_use_skills=False)
    clock = Clock()
    sched = AgentScheduler(agent, clock=clock, sleep=lambda _s: None)

    log: list[str] = []
    sched.add(
        "Summarize new error logs from the last hour.",
        every=3600,  # hourly
        name="hourly-error-digest",
        on_result=lambda r: log.append("hourly digest ran"),
    )
    sched.add(
        "Draft today's product-update tweet from this week's merged PRs.",
        at="09:00",  # every morning
        name="daily-social-post",
        on_result=lambda r: log.append("daily social post drafted"),
    )

    print("Registered jobs:")
    for job in sched.jobs:
        print(f"  • {job.name}: next run at t+{job.next_run - clock.now:.0f}s")

    print("\nSimulating 26 hours (fake clock — instant)…")
    for hour in range(26):
        clock.advance(3600)
        fired = sched.run_pending()
        if fired:
            print(f"  t+{hour + 1:>2}h → fired {len(fired)} job(s)")

    print("\nActivity log:")
    for line in log:
        print(f"  ✓ {line}")
    print(
        f"\nHourly digest fired {log.count('hourly digest ran')}× · "
        f"daily post fired {log.count('daily social post drafted')}× "
        "over the simulated day. ✓"
    )


if __name__ == "__main__":
    main()
