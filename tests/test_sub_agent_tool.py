from shipit_agent import SubAgentTool
from shipit_agent.llms import SimpleEchoLLM


def test_sub_agent_tool_uses_nested_llm() -> None:
    tool = SubAgentTool(llm=SimpleEchoLLM())
    result = tool.run(context=type("Ctx", (), {"prompt": "parent"})(), task="Summarize this")
    assert result.metadata["delegated"] is True
