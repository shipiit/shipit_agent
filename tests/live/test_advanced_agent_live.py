"""Real-model agent harness audit.

Run explicitly because this suite uses paid model calls and the public
DeepWiki MCP server:

    SHIPIT_RUN_LIVE_TESTS=1 .venv/bin/pytest -q -s \
      tests/live/test_advanced_agent_live.py

Set SHIPIT_AUDIT_MODELS to a comma-separated list to exercise the same agent
contract across providers supported by LiteLLM.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shipit_agent import Agent
from shipit_agent.builtins import get_builtin_tool_map
from shipit_agent.llms import LiteLLMChatLLM
from shipit_agent.mcp import MCPStreamableHTTPTransport, RemoteMCPServer


RUN_LIVE = os.getenv("SHIPIT_RUN_LIVE_TESTS") == "1"
DEFAULT_PROVIDER = Path(
    "/Users/rahulraj/Documents/MYWORK/AFTDRK/CACHE/DRK_CACHE_BACK/"
    "drk_cache/llm/bedrock_mantle_provider.py"
)
PROVIDER = Path(os.getenv("SHIPIT_MANTLE_PROVIDER", str(DEFAULT_PROVIDER)))
MODELS = [
    model.strip()
    for model in os.getenv(
        "SHIPIT_AUDIT_MODELS", "bedrock-mantle/google.gemma-4-26b-a4b"
    ).split(",")
    if model.strip()
]
DEEPWIKI_URL = "https://mcp.deepwiki.com/mcp"

pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="set SHIPIT_RUN_LIVE_TESTS=1 to make paid live model/MCP calls",
)


def _register_mantle_provider() -> None:
    if not PROVIDER.exists():
        pytest.skip(f"Bedrock Mantle provider not found: {PROVIDER}")
    module_name = "shipit_live_bedrock_mantle_provider"
    if module_name in sys.modules:
        return
    spec = importlib.util.spec_from_file_location(module_name, PROVIDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    module.ensure_registered()


def _llm(model: str) -> LiteLLMChatLLM:
    if model.startswith("bedrock-mantle/"):
        _register_mantle_provider()
    return LiteLLMChatLLM(model=model)


def _deepwiki() -> RemoteMCPServer:
    return RemoteMCPServer(
        name="deepwiki",
        transport=MCPStreamableHTTPTransport(DEEPWIKI_URL, timeout=120),
        include_server_in_tool_names=True,
    )


def _called(result) -> list[str]:
    return [
        str(event.payload.get("tool"))
        for event in result.events
        if event.type == "tool_called" and event.payload.get("tool")
    ]


def _completed_payload(result) -> dict:
    return next(
        event.payload for event in reversed(result.events)
        if event.type == "run_completed"
    )


def _diagnostics(result) -> str:
    events = [
        {
            "type": event.type,
            "message": event.message,
            "payload": event.payload,
        }
        for event in result.events
        if event.type
        in {
            "tool_call_healed",
            "tool_called",
            "tool_arguments_rejected",
            "tool_failed",
            "tool_completed",
            "run_completed",
        }
    ]
    return f"output={result.output!r}\ncalled={_called(result)!r}\nevents={events!r}"


@pytest.mark.parametrize("model", MODELS)
def test_live_simple_question_keeps_large_catalog_dormant(model: str) -> None:
    agent = Agent.with_builtins(
        llm=_llm(model),
        mcps=[_deepwiki()],
        auto_use_skills=False,
        max_iterations=6,
        project_root="/tmp",
    )

    result = agent.run("Reply with exactly: hello")

    called = _called(result)
    actual = [
        name for name in called
        if name not in {"tool_search", "call_tool", "todo", "give_up"}
    ]
    assert actual == [], called
    assert "hello" in result.output.lower()
    assert result.metadata["progressive_tool_context"] is True
    assert result.metadata["effective_code_mode"] is False
    assert result.metadata["hidden_tool_count"] > result.metadata["exposed_tool_count"]
    assert result.metadata["deferred_mcp_count"] == 1
    assert not any(
        event.type.startswith("mcp_discovery") for event in result.events
    )


@pytest.mark.parametrize("model", MODELS)
def test_live_deferred_mcp_research_uses_only_relevant_gateway(model: str) -> None:
    agent = Agent(
        llm=_llm(model),
        mcps=[_deepwiki()],
        auto_use_skills=False,
        max_iterations=10,
        tool_context_mode="auto",
        project_root="/tmp",
    )

    result = agent.run(
        "Use DeepWiki to identify the openai/openai-python classes or methods "
        "that decide retry eligibility and backoff. Cite only tool evidence."
    )

    called = _called(result)
    assert any(name.startswith("deepwiki__") for name in called), called
    assert "execute_code" not in called, called
    assert result.output.strip()
    completed = _completed_payload(result)
    assert completed["usage"]["total_tokens"] > 0
    assert completed["tool_context"]["hidden"] >= 1
    assert completed["tool_context"]["discovered_mcp_tools"] >= 1
    assert any(event.type == "mcp_discovery_completed" for event in result.events)


@pytest.mark.parametrize("model", MODELS)
def test_live_shell_read_edit_and_verify_in_real_workspace(
    model: str, tmp_path: Path
) -> None:
    (tmp_path / "calculator.py").write_text(
        "def divide(total, count):\n    return total * count\n",
        encoding="utf-8",
    )
    (tmp_path / "test_calculator.py").write_text(
        "from calculator import divide\n\n"
        "def test_divide():\n    assert divide(12, 3) == 4\n",
        encoding="utf-8",
    )
    tool_map = get_builtin_tool_map(llm=_llm(model), project_root=str(tmp_path))
    tools = [
        tool_map[name]
        for name in ("read_file", "grep_files", "edit_file", "bash")
    ]
    agent = Agent(
        llm=_llm(model),
        tools=tools,
        auto_use_skills=False,
        max_iterations=12,
        tool_context_mode="full",
        permission_mode="bypass",
        project_root=str(tmp_path),
        trace_id=f"live-shell-{model.replace('/', '-')}",
    )

    result = agent.run(
        "Inspect the calculator implementation and test. Fix the bug using "
        "edit_file, then run pytest with bash. Do not finish until the test passes."
    )

    verification = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    called = _called(result)
    assert verification.returncode == 0, (
        verification.stdout + verification.stderr + "\n" + _diagnostics(result)
    )
    assert "return total / count" in (tmp_path / "calculator.py").read_text()
    assert "edit_file" in called, called
    assert "bash" in called, called
    blocked = [
        event
        for event in result.events
        if event.payload.get("error") == "repeated_failure_blocked"
    ]
    assert len(blocked) <= 1, _diagnostics(result)


@pytest.mark.parametrize("model", MODELS)
def test_live_deep_task_routes_mcp_and_local_tools_without_code_mode(
    model: str, tmp_path: Path
) -> None:
    (tmp_path / "retry_policy.py").write_text(
        "class RetryPolicy:\n"
        "    max_attempts = 3\n"
        "    def should_retry(self, status):\n"
        "        return status in {429, 500, 502, 503}\n",
        encoding="utf-8",
    )
    tool_map = get_builtin_tool_map(llm=_llm(model), project_root=str(tmp_path))
    local = [tool_map[name] for name in ("read_file", "grep_files", "bash")]
    agent = Agent(
        llm=_llm(model),
        tools=local,
        mcps=[_deepwiki()],
        auto_use_skills=False,
        max_iterations=14,
        tool_context_mode="auto",
        project_root=str(tmp_path),
    )

    result = agent.run(
        "Compare the local RetryPolicy with openai/openai-python retry behavior. "
        "You must inspect retry_policy.py and use DeepWiki. Separate observed "
        "facts from inference and propose two concrete tests."
    )

    called = _called(result)
    assert any(name.startswith("deepwiki__") for name in called), called
    assert set(called) & {"read_file", "grep_files", "bash"}, called
    assert "execute_code" not in called, called
    assert result.output.strip()
    completed = _completed_payload(result)
    assert completed["tool_context"]["hidden"] >= 1
    assert completed["usage"]["total_tokens"] > 0
