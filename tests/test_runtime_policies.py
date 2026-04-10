from shipit_agent import Agent, FunctionTool, RetryPolicy, RouterPolicy
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall


def test_runtime_auto_plans_for_complex_prompts() -> None:
    class PassiveLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(content="done")

    agent = Agent(
        llm=PassiveLLM(),
        tools=[FunctionTool.from_callable(lambda goal: goal, name="noop"),],
        router_policy=RouterPolicy(auto_plan=True, long_prompt_threshold=10),
    )
    agent.tools.append(__import__("shipit_agent").PlannerTool())
    result = agent.run("Design and build a production workflow for this system.")
    assert any(event.type == "planning_started" for event in result.events)
    assert any(tool_result.name == "plan_task" for tool_result in result.tool_results)


def test_runtime_retries_llm_failures() -> None:
    class FlakyLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary failure")
            return LLMResponse(content="recovered")

    agent = Agent(
        llm=FlakyLLM(),
        retry_policy=RetryPolicy(max_llm_retries=1, retry_on_exceptions=(RuntimeError,)),
    )
    result = agent.run("hello")
    assert result.output == "recovered"
    assert any(event.type == "llm_retry" for event in result.events)
