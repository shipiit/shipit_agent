from shipit_agent import Agent, DEFAULT_AGENT_PROMPT, FunctionTool, RetryPolicy
from shipit_agent.exceptions import DuplicateToolError
from shipit_agent.llms import LLMResponse, SimpleEchoLLM
from shipit_agent.models import ToolCall
from shipit_agent.registry import ToolRegistry


def test_agent_runs_with_basic_prompt() -> None:
    agent = Agent(llm=SimpleEchoLLM(), prompt="System prompt")
    result = agent.run("Hello")
    assert "Hello" in result.output


def test_agent_uses_default_prompt_when_not_provided() -> None:
    agent = Agent(llm=SimpleEchoLLM())
    assert agent.prompt == DEFAULT_AGENT_PROMPT


def test_agent_stream_returns_events() -> None:
    agent = Agent(llm=SimpleEchoLLM(), prompt="System prompt")
    events = list(agent.stream("Hello"))
    assert events
    assert events[0].type == "run_started"
    assert events[0].to_dict()["type"] == "run_started"


def test_function_tool_schema_uses_callable_name() -> None:
    def add(a: int, b: int) -> str:
        return str(a + b)

    tool = FunctionTool.from_callable(add)
    schema = tool.schema()
    assert schema["function"]["name"] == "add"


def test_duplicate_tool_names_raise_error() -> None:
    def ping() -> str:
        return "pong"

    tool = FunctionTool.from_callable(ping, name="dup")
    other = FunctionTool.from_callable(ping, name="dup")

    try:
        ToolRegistry.build(tools=[tool, other])
    except DuplicateToolError:
        pass
    else:
        raise AssertionError("Expected DuplicateToolError")


def test_agent_executes_tool_calls() -> None:
    class ToolCallingLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(
                content="completed",
                tool_calls=[ToolCall(name="add", arguments={"a": 2, "b": 5})],
            )

    def add(a: int, b: int) -> str:
        return str(a + b)

    agent = Agent(
        llm=ToolCallingLLM(),
        prompt="Use tools when needed.",
        tools=[FunctionTool.from_callable(add)],
    )
    result = agent.run("compute")
    assert result.tool_results[0].output == "7"
    assert any(event.type == "tool_completed" for event in result.events)
    assistant_tool_message = next(message for message in result.messages if message.role == "assistant" and message.metadata.get("tool_calls"))
    assert assistant_tool_message.metadata["tool_calls"][0]["name"] == "add"
    tool_message = next(message for message in result.messages if message.role == "tool" and message.name == "add")
    assert tool_message.metadata["tool_call_id"].startswith("call_")


def test_agent_retries_flaky_tool() -> None:
    class StableLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(content="completed", tool_calls=[ToolCall(name="flaky", arguments={})])

    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("try again")
        return "ok"

    agent = Agent(
        llm=StableLLM(),
        tools=[FunctionTool.from_callable(flaky, name="flaky")],
        retry_policy=RetryPolicy(max_tool_retries=1, retry_on_exceptions=(RuntimeError,)),
    )
    result = agent.run("run flaky tool")
    assert result.tool_results[-1].output == "ok"
    assert any(event.type == "tool_retry" for event in result.events)


def test_agent_result_to_dict_contains_events_and_tools() -> None:
    agent = Agent(llm=SimpleEchoLLM(), prompt="System prompt")
    result = agent.run("Hello")
    payload = result.to_dict()
    assert "output" in payload
    assert "events" in payload
    assert payload["events"][-1]["type"] == "run_completed"
