"""Plan mode as a workflow: present_plan captures a plan, is allowed in plan
mode, and surfaces it for approval instead of being a bare gate.
"""

from __future__ import annotations

from shipit_agent.agent import Agent
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall
from shipit_agent.permissions import PermissionEngine
from shipit_agent.tools.base import ToolContext
from shipit_agent.tools.planner import PresentPlanTool


def test_present_plan_produces_an_interactive_plan_result():
    out = PresentPlanTool().run(
        ToolContext(prompt="", state={}),
        title="Refactor the auth module",
        steps=["Read auth.py", "Extract validate()", "Add tests"],
        notes="Assumes no external callers.",
    )
    assert out.metadata["interactive"] is True
    assert out.metadata["kind"] == "plan_approval"
    assert out.metadata["steps"][0] == "Read auth.py"
    assert "Refactor the auth module" in out.text
    assert "awaiting your approval" in out.text.lower()


def test_present_plan_rejects_an_empty_plan():
    out = PresentPlanTool().run(ToolContext(prompt="", state={}), title="X", steps=[])
    assert out.metadata.get("error") == "empty_plan"


def test_present_plan_is_allowed_in_plan_mode_but_writes_are_not():
    engine = PermissionEngine(mode="plan")
    assert engine.check("present_plan", {}).decision.value == "allow"
    assert engine.check("write_file", {"path": "x"}).decision.value == "deny"
    assert engine.check("read_file", {"path": "x"}).decision.value == "allow"


class PlanThenStopLLM:
    def __init__(self):
        self.turn = 0

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="present_plan", arguments={
                    "title": "Do the thing",
                    "steps": ["step one", "step two"],
                })],
            )
        return LLMResponse(content="Plan submitted; awaiting approval.")


def test_plan_mode_run_surfaces_the_plan_as_an_interactive_request():
    agent = Agent(
        llm=PlanThenStopLLM(),
        tools=[PresentPlanTool()],
        permission_mode="plan",
        auto_use_skills=False, auto_project_memory=False, skill_source=None,
        max_iterations=3,
    )
    events = list(agent.stream("refactor the module"))
    asks = [e for e in events if e.type == "interactive_request"]
    assert asks, "plan was not surfaced for approval"
    assert asks[0].payload.get("kind") == "plan_approval"
    plan = asks[0].payload.get("payload", {})
    assert plan.get("steps") == ["step one", "step two"]
