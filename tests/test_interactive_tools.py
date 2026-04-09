from shipit_agent import Agent, AskUserTool, HumanReviewTool
from shipit_agent.llms import LLMResponse
from shipit_agent.models import ToolCall


def test_ask_user_tool_emits_interactive_event() -> None:
    class AskUserLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(
                content="waiting",
                tool_calls=[ToolCall(name="ask_user", arguments={"question": "Choose one"})],
            )

    agent = Agent(llm=AskUserLLM(), prompt="Prompt", tools=[AskUserTool()])
    result = agent.run("start")
    assert any(event.type == "interactive_request" for event in result.events)


def test_human_review_tool_emits_interactive_event() -> None:
    class ReviewLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(
                content="review requested",
                tool_calls=[ToolCall(name="human_review", arguments={"summary": "Review this output"})],
            )

    agent = Agent(llm=ReviewLLM(), prompt="Prompt", tools=[HumanReviewTool()])
    result = agent.run("start")
    assert any(event.payload.get("kind") == "human_review" for event in result.events)
