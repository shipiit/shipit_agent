"""Live cross-provider smoke tests — one behaviour, every LLM.

Each test runs the same deferred-tools agent scenario against a real
provider and asserts the loop completed, a tool ran, and usage was
recorded. Skipped automatically when the provider's key is absent, so CI
without secrets stays green.

Run manually:

    OPENAI_API_KEY=... ANTHROPIC_API_KEY=... \
        python -m pytest tests/live -q -m "" -rs
"""

from __future__ import annotations

import os

import pytest

from shipit_agent.agent import Agent
from shipit_agent.policies import RetryPolicy
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.tool_search import ToolSearchTool


class WeatherTool:
    """A deterministic fake connector — deferred until searched for."""

    name = "weather_lookup"
    description = "Look up the current weather for a city."

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }

    def run(self, context, **kwargs) -> ToolOutput:
        city = kwargs.get("city", "unknown")
        return ToolOutput(text=f"Weather in {city}: 21°C, clear skies.", metadata={})


def _run_scenario(llm) -> None:
    agent = Agent(
        llm=llm,
        tools=[ToolSearchTool(), WeatherTool()],
        deferred_tools=True,
        max_iterations=5,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        retry_policy=RetryPolicy(request_timeout=120.0),
    )
    result = agent.run(
        "Find the right tool and tell me the current weather in Paris. "
        "Answer with the temperature."
    )
    tool_names = {r.name for r in result.tool_results}
    if "weather_lookup" not in tool_names or not result.output:
        # Live-model debugging: the assertion message must show what the
        # model actually did, or a flake is undiagnosable after the fact.
        trace = "\n".join(
            f"{e.type}: {str(e.payload)[:160]}"
            for e in result.events
            if e.type
            in ("step_started", "tool_called", "tool_call_healed", "final_answer")
        )
        raise AssertionError(
            f"scenario failed; ran={tool_names} output={result.output[:200]!r}\n{trace}"
        )
    assert "21" in result.output or "Paris" in result.output
    usage_ticks = [e for e in result.events if e.type == "usage_tick"]
    assert usage_ticks, "usage must be recorded"
    assert usage_ticks[-1].payload["usage"].get("total_tokens", 0) > 0


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_live_openai():
    from shipit_agent.llms import OpenAIChatLLM

    _run_scenario(OpenAIChatLLM(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")))


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
def test_live_anthropic():
    from shipit_agent.llms import AnthropicChatLLM

    _run_scenario(
        AnthropicChatLLM(
            model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        )
    )


@pytest.mark.skipif(
    not (os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("BEDROCK_MODEL")),
    reason="AWS credentials / BEDROCK_MODEL not set",
)
def test_live_bedrock():
    from shipit_agent.llms import BedrockChatLLM

    _run_scenario(BedrockChatLLM(model=os.environ["BEDROCK_MODEL"]))


def _native_mantle_available() -> bool:
    try:
        from shipit_agent.llms.litellm_adapter import _litellm_supports_bedrock_mantle

        return _litellm_supports_bedrock_mantle()
    except Exception:
        return False


@pytest.mark.skipif(
    not (_native_mantle_available() and os.getenv("BEDROCK_MANTLE_API_KEY")),
    reason="needs litellm's native bedrock_mantle provider + BEDROCK_MANTLE_API_KEY",
)
def test_live_bedrock_mantle_native():
    """Gemma on Bedrock Mantle through LiteLLM's NATIVE provider —
    https://docs.litellm.ai/docs/providers/bedrock_mantle — no custom
    provider checkout required. Auth is a Bedrock API key (Bearer), so the
    test only runs when one is configured; SigV4-only environments are
    covered by test_live_bedrock_mantle_gemma below."""
    from shipit_agent.llms import BedrockChatLLM

    model = os.getenv("SHIPIT_AUDIT_MODEL", "bedrock_mantle/google.gemma-4-26b-a4b")
    _run_scenario(BedrockChatLLM(model=model))


_MANTLE_PROVIDER = os.getenv(
    "SHIPIT_MANTLE_PROVIDER",
    "/Users/rahulraj/Documents/MYWORK/AFTDRK/CACHE/DRK_CACHE_BACK"
    "/drk_cache/llm/bedrock_mantle_provider.py",
)


@pytest.mark.skipif(
    not os.path.exists(_MANTLE_PROVIDER),
    reason="bedrock-mantle provider checkout not found",
)
def test_live_bedrock_mantle_gemma():
    """The weak-model gauntlet: Gemma via the custom bedrock-mantle provider.

    This is the exact model whose 31k-token turns motivated the token work —
    deferred tools, healing, and the argument gate all get exercised here.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "bedrock_mantle_provider", _MANTLE_PROVIDER
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bedrock_mantle_provider"] = module
    spec.loader.exec_module(module)
    module.ensure_registered()

    from shipit_agent.llms import LiteLLMChatLLM

    model = os.getenv("SHIPIT_AUDIT_MODEL", "bedrock-mantle/google.gemma-4-26b-a4b")
    _run_scenario(LiteLLMChatLLM(model=model))


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set")
def test_live_groq():
    from shipit_agent.llms import GroqChatLLM

    _run_scenario(
        GroqChatLLM(model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    )


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
def test_live_gemini():
    from shipit_agent.llms import GeminiChatLLM

    _run_scenario(
        GeminiChatLLM(model=os.getenv("GEMINI_MODEL", "gemini/gemini-1.5-pro"))
    )
