"""The automatic planner step is opt-in, and never repeats the whole prompt.

It ran on any long prompt or one mentioning "build", "create", "plan"...,
added a fixed five-step template, and began it with the entire prompt;
in a host that attaches context to the turn (a skills catalog, files),
that context was sent twice from then on. The model can still call
plan_task itself.
"""

from __future__ import annotations

from typing import Any

from shipit_agent import Agent
from shipit_agent.core.policies import RouterPolicy
from shipit_agent.llms.base import LLMResponse
from shipit_agent.tools.planner.planner_tool import PlannerTool


class _Answers:
    model = "claude-sonnet-5-5"

    def __init__(self) -> None:
        self.users: list[list[str]] = []

    def complete(self, *, messages: Any, **_: Any) -> LLMResponse:
        self.users.append([str(m.content) for m in messages if m.role == "user"])
        return LLMResponse(content="done")


PROMPT = "Build and create a plan to design the new billing service. " + "Context line. " * 300


def test_no_planner_step_by_default() -> None:
    llm = _Answers()
    result = Agent(llm=llm, tools=[PlannerTool()]).run(PROMPT)
    assert not any(event.type == "planning_started" for event in result.events)
    assert not any("[Planner output]" in text for text in llm.users[0])


def test_an_opted_in_planner_does_not_repeat_a_long_prompt() -> None:
    llm = _Answers()
    Agent(llm=llm, tools=[PlannerTool()], router_policy=RouterPolicy(auto_plan=True)).run(PROMPT)
    planner = [text for text in llm.users[0] if text.startswith("[Planner output]")]
    assert len(planner) == 1
    assert len(planner[0]) < 800
    assert PROMPT not in planner[0]
