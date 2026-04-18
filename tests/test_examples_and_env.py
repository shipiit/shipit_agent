from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from shipit_agent.llms import LLMResponse, LiteLLMChatLLM, ShipitLLM, VertexAIChatLLM
from shipit_agent.models import ToolCall

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = ROOT / "examples" / "run_multi_tool_agent.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_multi_tool_agent", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_example_build_llm_from_env_supports_shipit(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("SHIPIT_LLM_PROVIDER", "shipit")
    llm = module.build_llm_from_env()
    assert isinstance(llm, ShipitLLM)


def test_example_build_llm_from_env_validates_bedrock(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("SHIPIT_LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("AWS_REGION_NAME", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    fake_boto3 = SimpleNamespace(
        session=SimpleNamespace(Session=lambda: SimpleNamespace(region_name=None))
    )
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    try:
        module.build_llm_from_env()
    except RuntimeError as exc:
        assert "Bedrock requires AWS_REGION_NAME" in str(exc)
    else:
        raise AssertionError("Expected Bedrock environment validation error")


def test_example_build_llm_from_env_supports_vertex_json_credentials(
    monkeypatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("SHIPIT_LLM_PROVIDER", "vertex")
    monkeypatch.setenv("SHIPIT_VERTEX_CREDENTIALS_FILE", "/tmp/vertex-sa.json")
    monkeypatch.setenv("VERTEXAI_PROJECT", "demo-project")
    monkeypatch.setenv("VERTEXAI_LOCATION", "us-central1")
    llm = module.build_llm_from_env()
    assert isinstance(llm, VertexAIChatLLM)
    assert llm.model == "vertex_ai/gemini-1.5-pro"


def test_example_build_llm_from_env_falls_back_to_bedrock_when_anthropic_sdk_missing(
    monkeypatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("SHIPIT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "demo-key")
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")

    class FakeBedrock:
        def __init__(self, model):
            self.model = model

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    from shipit_agent.llms import factory as factory_module

    monkeypatch.setattr(factory_module, "AnthropicChatLLM", broken_anthropic)
    monkeypatch.setattr(factory_module, "BedrockChatLLM", FakeBedrock)

    llm = module.build_llm_from_env()
    assert isinstance(llm, FakeBedrock)
    assert llm.model == "bedrock/openai.gpt-oss-120b-1:0"


def test_example_build_llm_from_env_keeps_explicit_anthropic_errors(
    monkeypatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "demo-key")

    def broken_anthropic(*args, **kwargs):
        raise RuntimeError("Install `anthropic` to use AnthropicChatLLM.")

    from shipit_agent.llms import factory as factory_module

    monkeypatch.setattr(factory_module, "AnthropicChatLLM", broken_anthropic)

    try:
        module.build_llm_from_env("anthropic")
    except RuntimeError as exc:
        assert "Install `anthropic`" in str(exc)
    else:
        raise AssertionError("Expected explicit anthropic provider to keep failing")


def test_example_build_llm_from_env_supports_generic_litellm(monkeypatch) -> None:
    module = _load_module()
    monkeypatch.setenv("SHIPIT_LLM_PROVIDER", "litellm")
    monkeypatch.setenv("SHIPIT_LITELLM_MODEL", "openrouter/openai/gpt-4o-mini")
    monkeypatch.setenv("SHIPIT_LITELLM_API_BASE", "http://localhost:4000")
    monkeypatch.setenv("SHIPIT_LITELLM_API_KEY", "litellm-key")
    llm = module.build_llm_from_env()
    assert isinstance(llm, LiteLLMChatLLM)
    assert llm.model == "openrouter/openai/gpt-4o-mini"
    assert llm.completion_kwargs["api_base"] == "http://localhost:4000"
    assert llm.completion_kwargs["api_key"] == "litellm-key"


def test_example_build_demo_agent_adds_function_tools(tmp_path) -> None:
    module = _load_module()
    agent = module.build_demo_agent(llm=ShipitLLM(), workspace_root=str(tmp_path))
    tool_names = {tool.name for tool in agent.tools}
    assert "project_context" in tool_names
    assert "add_numbers" in tool_names


def test_example_agent_can_execute_documented_tool_pattern(tmp_path) -> None:
    module = _load_module()

    class ToolCallingLLM:
        def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
            return LLMResponse(
                content="completed",
                tool_calls=[
                    ToolCall(name="project_context", arguments={}),
                    ToolCall(name="add_numbers", arguments={"a": 2, "b": 3}),
                ],
            )

    agent = module.build_demo_agent(llm=ToolCallingLLM(), workspace_root=str(tmp_path))
    result = agent.run("Use the tools")
    outputs = {item.name: item.output for item in result.tool_results}
    assert "project_context" in outputs
    assert outputs["add_numbers"] == "5"


def test_env_example_mentions_supported_provider_keys() -> None:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "SHIPIT_LLM_PROVIDER=bedrock" in content
    assert "AWS_REGION_NAME=us-east-1" in content
    assert "OPENAI_API_KEY=" in content
    assert "ANTHROPIC_API_KEY=" in content
    assert "SHIPIT_VERTEX_CREDENTIALS_FILE=" in content
    assert "SHIPIT_LITELLM_API_BASE=" in content


def test_examples_package_exports_demo_builders() -> None:
    sys.path.insert(0, str(ROOT))
    try:
        from examples import build_demo_agent, build_llm_from_env
    finally:
        sys.path = [path for path in sys.path if path != str(ROOT)]

    assert callable(build_llm_from_env)
    assert callable(build_demo_agent)
