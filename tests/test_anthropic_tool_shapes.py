"""shipit's own tools reach Anthropic as client tools, in Anthropic's shape.

Every shipit tool schema is OpenAI-shaped, `{"type": "function", "function":
{...}}`. A tool with a top-level `type` was taken for a server tool (web
search, code execution) and forwarded as-is, so the first live run of the
native adapter was rejected: "tools.0: Input tag 'function' found using
'type' does not match any of the expected tags".
"""

from __future__ import annotations

from pathlib import Path

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.server_tools import is_server_tool
from shipit_agent.tools.bash.bash_tool import BashTool


def test_an_openai_shaped_function_tool_is_a_client_tool() -> None:
    assert not is_server_tool({"type": "function", "function": {"name": "bash", "parameters": {}}})
    assert not is_server_tool({"name": "flat", "parameters": {}})
    assert is_server_tool({"type": "web_search_20250305", "name": "web_search", "max_uses": 3})


def test_a_real_shipit_tool_is_sent_as_name_description_and_input_schema(tmp_path: Path) -> None:
    schema = BashTool(root_dir=tmp_path).schema()
    kwargs = AnthropicChatLLM(model="claude-sonnet-5-5", prompt_caching=False)._build_request_kwargs(
        messages=[Message(role="user", content="hi")], tools=[schema], system_prompt="s", documents=None)
    sent = kwargs["tools"][0]
    assert set(sent) == {"name", "description", "input_schema"}
    assert sent["name"] == "bash" and sent["input_schema"]["properties"]["command"]["type"] == "string"


def test_server_tools_still_pass_through_beside_client_tools(tmp_path: Path) -> None:
    server = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
    kwargs = AnthropicChatLLM(model="claude-sonnet-5-5", prompt_caching=False)._build_request_kwargs(
        messages=[Message(role="user", content="hi")], tools=[BashTool(root_dir=tmp_path).schema(), server],
        system_prompt="s", documents=None)
    assert kwargs["tools"][1] == server and "type" not in kwargs["tools"][0]
