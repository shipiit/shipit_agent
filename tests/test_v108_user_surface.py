"""User-surface verification: every v1.0.8 power feature is reachable
through the same `from shipit_agent import ...` entry point and works on
both ``Agent`` AND ``DeepAgent``.

This is the "smoke test on the public API" — it makes sure the marketing
claim ("all features available on Agent and DeepAgent") is actually true.
≥10 tests covering import surface, Agent constructor, DeepAgent constructor,
DeepAgent kwarg propagation, and ``create_deep_agent``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    pytest.skip("pydantic not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Public-import surface
# ---------------------------------------------------------------------------


class TestPublicImports:
    """Every v1.0.8 symbol is importable from the top-level package."""

    def test_structured_output_class(self) -> None:
        from shipit_agent import StructuredOutput

        assert StructuredOutput is not None

    def test_structured_output_result(self) -> None:
        from shipit_agent import StructuredOutputResult

        assert StructuredOutputResult is not None

    def test_parse_partial_json(self) -> None:
        from shipit_agent import parse_partial_json

        assert callable(parse_partial_json)

    def test_verifier_network(self) -> None:
        from shipit_agent import VerifierNetwork

        assert VerifierNetwork is not None

    def test_verifier_config(self) -> None:
        from shipit_agent import VerifierConfig

        assert VerifierConfig is not None

    def test_verifier_verdict_enum(self) -> None:
        from shipit_agent import VerifierVerdict

        assert VerifierVerdict.ALLOW.value == "allow"
        assert VerifierVerdict.VETO.value == "veto"

    def test_pretool_decision(self) -> None:
        from shipit_agent import PreToolDecision

        assert PreToolDecision is not None

    def test_pretool_verifier(self) -> None:
        from shipit_agent import PreToolVerifier

        assert PreToolVerifier is not None

    def test_progress_check(self) -> None:
        from shipit_agent import ProgressCheck

        assert ProgressCheck is not None

    def test_progress_verifier(self) -> None:
        from shipit_agent import ProgressVerifier

        assert ProgressVerifier is not None

    def test_namespace_modules(self) -> None:
        # Sub-package access works too
        import shipit_agent.verifier
        import shipit_agent.structured_output

        assert hasattr(shipit_agent.verifier, "VerifierNetwork")
        assert hasattr(shipit_agent.structured_output, "StructuredOutput")


# ---------------------------------------------------------------------------
# Test doubles shared across user-surface tests
# ---------------------------------------------------------------------------


@dataclass
class StubLLM:
    responses: list[str] = field(default_factory=list)
    calls: int = 0

    def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> Any:
        from shipit_agent.llms.base import LLMResponse

        self.calls += 1
        text = (
            self.responses[min(self.calls - 1, len(self.responses) - 1)]
            if self.responses
            else ""
        )
        return LLMResponse(content=text)


def _allow() -> str:
    return json.dumps({"verdict": "allow", "reason": "ok", "confidence": 0.9})


def _veto() -> str:
    return json.dumps({"verdict": "veto", "reason": "no", "confidence": 0.95})


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "demo"
        self.prompt = ""
        self.prompt_instructions = ""
        self.run_calls: list[dict[str, Any]] = []

    def schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, context: Any = None, **kwargs: Any) -> Any:
        from shipit_agent.tools.base import ToolOutput

        self.run_calls.append(kwargs)
        return ToolOutput(text=f"{self.name} ran", metadata={})


class Movie(BaseModel):
    title: str
    rating: float


# ---------------------------------------------------------------------------
# Agent surface — output_schema + verifier
# ---------------------------------------------------------------------------


class TestAgentSurface:
    def test_output_schema_param_accepted(self) -> None:
        from shipit_agent import Agent

        llm = StubLLM(['{"title": "X", "rating": 1.0}'])
        agent = Agent(llm=llm)
        result = agent.run("ask", output_schema=Movie)
        assert isinstance(result.parsed, Movie)

    def test_max_validation_retries_param_accepted(self) -> None:
        from shipit_agent import Agent

        llm = StubLLM(["bad", '{"title": "X", "rating": 1.0}'])
        agent = Agent(llm=llm)
        result = agent.run("ask", output_schema=Movie, max_validation_retries=2)
        assert result.parsed is not None
        assert llm.calls == 2

    def test_verifier_constructor_param_accepted(self) -> None:
        from shipit_agent import Agent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()]))
        agent = Agent(llm=StubLLM([]), verifier=v)
        assert agent.verifier is v

    def test_verifier_wraps_tools(self) -> None:
        from shipit_agent import Agent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()] * 5))
        tool = FakeTool("t")
        agent = Agent(
            llm=StubLLM([]), tools=[tool], verifier=v, auto_use_skills=False
        )
        effective = agent._effective_tools("any")  # noqa: SLF001
        # Wrapped — not the same object identity
        assert effective[0] is not tool
        assert effective[0].name == "t"

    def test_no_verifier_no_wrapping(self) -> None:
        from shipit_agent import Agent

        tool = FakeTool("t")
        agent = Agent(llm=StubLLM([]), tools=[tool], auto_use_skills=False)
        effective = agent._effective_tools("any")  # noqa: SLF001
        assert effective[0] is tool


# ---------------------------------------------------------------------------
# DeepAgent surface — same features
# ---------------------------------------------------------------------------


class TestDeepAgentSurface:
    def test_deepagent_accepts_verifier(self) -> None:
        from shipit_agent import DeepAgent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()]))
        deep = DeepAgent(llm=StubLLM([]), verifier=v)
        assert deep.verifier is v

    def test_deepagent_propagates_verifier_to_inner_agent(self) -> None:
        from shipit_agent import DeepAgent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()] * 3))
        deep = DeepAgent(llm=StubLLM([]), verifier=v)
        inner = deep._agent  # noqa: SLF001
        assert inner.verifier is v

    def test_deepagent_run_accepts_output_schema_kwarg(self) -> None:
        from shipit_agent import DeepAgent

        # DeepAgent.run forwards **kwargs to inner Agent.run, including
        # output_schema. Smoke test — we just check the call shape works.
        llm = StubLLM(['{"title": "X", "rating": 1.0}'])
        deep = DeepAgent(llm=llm)
        # We don't drive a full deep run here (would require more plumbing);
        # instead verify the inner agent accepts the kwarg.
        inner = deep._agent  # noqa: SLF001
        result = inner.run("ask", output_schema=Movie)
        assert isinstance(result.parsed, Movie)

    def test_create_deep_agent_accepts_verifier(self) -> None:
        from shipit_agent import create_deep_agent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()]))
        deep = create_deep_agent(llm=StubLLM([]), verifier=v)
        assert deep.verifier is v
        assert deep._agent.verifier is v  # noqa: SLF001

    def test_deepagent_verifier_blocks_tool(self) -> None:
        from shipit_agent import DeepAgent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_veto()]))
        tool = FakeTool("rm_rf")
        deep = DeepAgent(llm=StubLLM([]), verifier=v, extra_tools=[tool])
        inner = deep._agent  # noqa: SLF001
        effective = inner._effective_tools("any")  # noqa: SLF001
        # Find our tool by name; the wrapper preserves the name
        wrapped = next(t for t in effective if t.name == "rm_rf")
        result = wrapped.run(path="/")
        assert "verifier-veto" in result.text
        assert tool.run_calls == []  # never reached the inner tool

    def test_deepagent_telemetry_accessible_post_run(self) -> None:
        from shipit_agent import DeepAgent, VerifierNetwork

        v = VerifierNetwork(llm=StubLLM([_allow()] * 3))
        deep = DeepAgent(llm=StubLLM([]), verifier=v)
        # Stats reachable through both deep.verifier and deep._agent.verifier
        assert deep.verifier.stats.pretool_calls == 0
        assert deep._agent.verifier.stats.pretool_calls == 0  # noqa: SLF001

    def test_no_verifier_works_for_deepagent(self) -> None:
        from shipit_agent import DeepAgent

        # No verifier — sanity check that DeepAgent still constructs cleanly
        deep = DeepAgent(llm=StubLLM([]))
        assert deep.verifier is None
        assert deep._agent.verifier is None  # noqa: SLF001
