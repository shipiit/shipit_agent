"""
21 — A "growth + deep research" agent (composition, not magic).

shipit_agent is primitives you compose. A powerful growth/research agent is
just the right built-ins wired together — no new infrastructure:

    research   →  web_search / research_brief   (find what's trending & true)
    draft      →  the LLM                        (write the post / report)
    schedule   →  AgentScheduler                 (recurring, daily, cron)
    publish    →  custom_api                     (POST to ANY platform API you
                                                   have credentials for)

That last step is deliberately generic: shipit does NOT ship brittle
Twitter/Instagram OAuth clients. You point `custom_api` at whatever endpoint
you use (an X API app, a Buffer/Typefully/Zapier webhook, your own backend)
and the agent fills in the content. Honest and un-brittle.

This file has two parts:
  • build_growth_agent()   — the real agent (needs an LLM + web-search key).
  • demo()                 — runs offline, printing the pipeline it would run.

Run:
    python examples/21_growth_research_agent.py
"""

from __future__ import annotations

import os

from shipit_agent import Agent, AgentScheduler
from shipit_agent.integrations import CredentialRecord, InMemoryCredentialStore
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools import CustomAPITool


# ── The real thing ────────────────────────────────────────────────────────
def build_growth_agent(llm, *, publish_base_url: str, publish_token: str):
    """A research-and-publish agent with the full built-in toolbox.

    `with_builtins` attaches web_search, research_brief, file ops, code
    execution, memory, todo, and more. We add a `publish` tool (a
    CustomAPITool bound to your posting endpoint via a credential record)
    so the agent can actually post.
    """
    creds = InMemoryCredentialStore()
    creds.set(
        CredentialRecord(
            key="publish",
            provider="custom_api",
            secrets={"token": publish_token},
            metadata={"base_url": publish_base_url},
        )
    )
    publisher = CustomAPITool(
        name="publish",
        credential_key="publish",
        credential_store=creds,
        description="POST the finished content to the publishing endpoint.",
    )
    return Agent.with_builtins(
        llm=llm,
        web_search_provider=os.getenv("SHIPIT_SEARCH_PROVIDER", "duckduckgo"),
        web_search_api_key=os.getenv("SHIPIT_SEARCH_API_KEY"),
        tools=[publisher],
        name="growth-agent",
    )


def schedule_growth_jobs(agent) -> AgentScheduler:
    """Recurring content + research jobs — the 'set it and it works' layer."""
    sched = AgentScheduler(agent)
    post_prompt = (
        "Research the top 3 trending topics in AI agents this week with "
        "web_search, then draft one insightful X post (<280 chars) and "
        "publish it via the `publish` tool. Return the posted text."
    )
    try:
        # 09:00 on weekdays — cron needs the optional `croniter` package.
        sched.add(post_prompt, cron="0 9 * * 1-5", name="weekday-thought-leadership")
    except ImportError:
        sched.add(post_prompt, at="09:00", name="daily-thought-leadership")
    sched.add(
        "Build a research_brief on our top competitor's latest launches and "
        "save a summary to memory for next week's planning.",
        at="08:00",                   # every morning
        name="daily-competitor-brief",
    )
    return sched


# ── Offline demo (no keys required) ───────────────────────────────────────
class _ExplainLLM:
    """Offline stand-in that narrates the pipeline instead of calling APIs."""

    def complete(self, *, messages, **_kwargs) -> LLMResponse:
        return LLMResponse(content="[draft] Ship faster with agentic workflows.")


def demo() -> None:
    print("Growth + deep-research agent — the composition\n")
    print("  research  → web_search / research_brief")
    print("  draft     → the LLM")
    print("  schedule  → AgentScheduler (daily / cron)")
    print("  publish   → custom_api  (any HTTP API you have creds for)\n")

    have_keys = bool(os.getenv("SHIPIT_PUBLISH_URL"))
    if not have_keys:
        print("To run for real, set:")
        print("  export SHIPIT_PUBLISH_URL=...       # your posting endpoint")
        print("  export SHIPIT_PUBLISH_TOKEN=...     # its auth token")
        print("  export SHIPIT_SEARCH_API_KEY=...    # optional, for a real")
        print("                                      #   web-search backend")
        print("\nRegistering the recurring jobs offline to show the schedule:\n")

    agent = Agent(llm=_ExplainLLM(), auto_use_skills=False)
    sched = schedule_growth_jobs(agent)
    for job in sched.jobs:
        when = job.cron or (f"daily {job.at}" if job.at else f"every {job.interval_seconds}s")
        print(f"  • {job.name:<28} → {when}")
    print("\nSame pattern scales to LinkedIn, a newsletter, a Slack digest — "
          "point `publish` at a different endpoint. ✓")


if __name__ == "__main__":
    demo()
