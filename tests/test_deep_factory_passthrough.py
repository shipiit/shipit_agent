"""Regression tests for DeepAgent goal/reflective passthrough (DEEP-3).

_build_goal_agent / _build_reflective_agent must forward memory, history,
and verifier — previously they were silently dropped.
"""

from __future__ import annotations

from shipit_agent.deep.deep_agent.factory import DeepAgent
from shipit_agent.models import Message
from shipit_agent.deep.goal_agent import Goal


class _DummyLLM:
    def complete(self, **kwargs):  # pragma: no cover
        from shipit_agent.llms import LLMResponse

        return LLMResponse(content="{}")


class _DummyVerifier:
    def wrap_tools(self, tools):
        return tools


def test_goal_agent_receives_memory_history_verifier():
    verifier = _DummyVerifier()
    history = [Message(role="user", content="earlier")]
    da = DeepAgent(
        llm=_DummyLLM(),
        goal=Goal(objective="do it"),
        memory="MEM-SENTINEL",
        history=history,
        verifier=verifier,
    )
    inner = da._build_goal_agent()
    assert inner.memory == "MEM-SENTINEL"
    assert inner.agent_kwargs.get("verifier") is verifier
    assert inner.agent_kwargs.get("history") == history


def test_reflective_agent_receives_memory_history_verifier():
    verifier = _DummyVerifier()
    history = [Message(role="user", content="earlier")]
    da = DeepAgent(
        llm=_DummyLLM(),
        reflect=True,
        memory="MEM-SENTINEL",
        history=history,
        verifier=verifier,
    )
    inner = da._build_reflective_agent()
    assert inner.memory == "MEM-SENTINEL"
    assert inner.agent_kwargs.get("verifier") is verifier
    assert inner.agent_kwargs.get("history") == history


def test_goal_agent_no_history_when_empty():
    da = DeepAgent(llm=_DummyLLM(), goal=Goal(objective="x"))
    inner = da._build_goal_agent()
    # No static history and no memory -> no spurious history kwarg.
    assert "history" not in inner.agent_kwargs
    assert inner.memory is None
