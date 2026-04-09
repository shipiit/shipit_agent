from shipit_agent import ToolRunner, construct_tool_registry, get_builtin_tools
from shipit_agent.llms import BedrockChatLLM, GeminiChatLLM, SimpleEchoLLM, VertexAIChatLLM
from shipit_agent.models import ToolCall
from shipit_agent.tools import FunctionTool, ToolContext


def test_construct_tool_registry_builds_registry() -> None:
    def add(a: int, b: int) -> str:
        return str(a + b)

    registry = construct_tool_registry(tools=[FunctionTool.from_callable(add)])
    assert registry.get("add") is not None


def test_tool_runner_executes_tool_call() -> None:
    def add(a: int, b: int) -> str:
        return str(a + b)

    registry = construct_tool_registry(tools=[FunctionTool.from_callable(add)])
    runner = ToolRunner(registry)
    result = runner.run_tool_call(
        ToolCall(name="add", arguments={"a": 1, "b": 2}),
        ToolContext(prompt="sum"),
    )
    assert result.output == "3"


def test_get_builtin_tools_includes_expected_capabilities() -> None:
    tools = get_builtin_tools(llm=SimpleEchoLLM())
    tool_names = {tool.name for tool in tools}
    assert "web_search" in tool_names
    assert "open_url" in tool_names
    assert "sub_agent" in tool_names


def test_bedrock_wrapper_uses_litellm_model_namespace() -> None:
    llm = BedrockChatLLM()
    assert llm.model == "bedrock/openai.gpt-oss-120b-1:0"


def test_gemini_wrapper_uses_litellm_model_namespace() -> None:
    llm = GeminiChatLLM()
    assert llm.model.startswith("gemini/")


def test_vertex_wrapper_uses_litellm_model_namespace() -> None:
    llm = VertexAIChatLLM()
    assert llm.model.startswith("vertex_ai/")
