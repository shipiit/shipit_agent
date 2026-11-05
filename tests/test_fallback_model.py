"""``fallback_model``: when the model fails after its retries, use the next one.

As in the Claude Agent SDK, the option takes a model id or a comma-separated
list of them; shipit also takes adapter instances.
"""

from __future__ import annotations

from typing import Any

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.models import ToolCall
from shipit_agent.core.policies import RetryPolicy
from shipit_agent.llms.base import LLMResponse

NO_WAIT = RetryPolicy(llm_retry_base_delay=0)


class _Model:
    """Fails for the model ids in *down*; answers for any other."""

    def __init__(self, model: str, down: set[str], calls: list[str]) -> None:
        self.model = model
        self.down = down
        self.calls = calls

    def complete(self, **_: Any) -> LLMResponse:
        self.calls.append(self.model)
        if self.model in self.down:
            raise ConnectionError(f"{self.model} is overloaded")
        return LLMResponse(content=f"answered by {self.model}")


def _echo(text: str = "") -> str:
    """Echo the text."""
    return f"echo:{text}"


def test_a_model_id_fallback_answers_when_the_primary_is_down() -> None:
    calls: list[str] = []
    llm = _Model("primary", {"primary"}, calls)
    result = Agent(llm=llm, fallback_model="backup", retry_policy=NO_WAIT).run("hi")
    assert result.output == "answered by backup"


def test_the_primary_is_retried_before_falling_back() -> None:
    calls: list[str] = []
    llm = _Model("primary", {"primary"}, calls)
    Agent(llm=llm, fallback_model="backup", retry_policy=NO_WAIT).run("hi")
    assert calls == ["primary", "primary", "primary", "backup"]


def test_a_comma_separated_list_is_tried_in_order() -> None:
    calls: list[str] = []
    llm = _Model("primary", {"primary", "second"}, calls)
    policy = RetryPolicy(llm_retry_base_delay=0, max_llm_retries=0)
    result = Agent(llm=llm, fallback_model="second, third", retry_policy=policy).run("hi")
    assert result.output == "answered by third"
    assert calls == ["primary", "second", "third"]


def test_an_adapter_instance_can_be_the_fallback() -> None:
    calls: list[str] = []
    backup = _Model("other-provider", set(), calls)
    llm = _Model("primary", {"primary"}, calls)
    result = Agent(llm=llm, fallback_model=backup, retry_policy=NO_WAIT).run("hi")
    assert result.output == "answered by other-provider"


def test_the_switch_is_reported_as_an_event() -> None:
    llm = _Model("primary", {"primary"}, [])
    result = Agent(llm=llm, fallback_model="backup", retry_policy=NO_WAIT).run("hi")
    switches = [e for e in result.events if e.type == "model_fallback"]
    assert len(switches) == 1
    assert switches[0].payload["from_model"] == "primary"
    assert switches[0].payload["to_model"] == "backup"
    assert "overloaded" in switches[0].payload["error"]


def test_the_run_stays_on_the_fallback_after_switching() -> None:
    calls: list[str] = []

    class _Primary(_Model):
        def complete(self, **kwargs: Any) -> LLMResponse:
            if self.model == "backup" and calls.count("backup") == 0:
                calls.append(self.model)
                return LLMResponse(content="", tool_calls=[ToolCall(name="echo", arguments={})])
            return super().complete(**kwargs)

    llm = _Primary("primary", {"primary"}, calls)
    policy = RetryPolicy(llm_retry_base_delay=0, max_llm_retries=0)
    tools = [FunctionTool.from_callable(_echo, name="echo")]
    Agent(llm=llm, tools=tools, fallback_model="backup", retry_policy=policy).run("hi")
    assert calls == ["primary", "backup", "backup"]


def test_the_agent_keeps_its_primary_model_for_the_next_run() -> None:
    calls: list[str] = []
    llm = _Model("primary", {"primary"}, calls)
    agent = Agent(llm=llm, fallback_model="backup", retry_policy=NO_WAIT)
    agent.run("one")
    assert agent.llm.model == "primary"


def test_when_every_model_fails_the_last_error_is_raised() -> None:
    llm = _Model("primary", {"primary", "backup"}, [])
    with pytest.raises(ConnectionError, match="backup is overloaded"):
        Agent(llm=llm, fallback_model="backup", retry_policy=NO_WAIT).run("hi")


def test_without_a_fallback_the_error_is_raised_as_before() -> None:
    llm = _Model("primary", {"primary"}, [])
    with pytest.raises(ConnectionError, match="primary is overloaded"):
        Agent(llm=llm, retry_policy=NO_WAIT).run("hi")


@pytest.mark.parametrize("spec", ["", " , ", []])
def test_an_empty_fallback_means_none(spec: Any) -> None:
    llm = _Model("primary", {"primary"}, [])
    with pytest.raises(ConnectionError):
        Agent(llm=llm, fallback_model=spec, retry_policy=NO_WAIT).run("hi")


def test_a_model_id_needs_an_adapter_with_a_model_attribute() -> None:
    class _NoModel:
        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(content="x")

    with pytest.raises(ValueError, match="fallback_model"):
        Agent(llm=_NoModel(), fallback_model="backup")


def test_a_fallback_that_is_not_a_model_is_refused() -> None:
    with pytest.raises(TypeError, match="fallback_model"):
        Agent(llm=_Model("primary", set(), []), fallback_model=42)


def _bedrock_route(llm: Any) -> str:
    """Mantle (a delegate, or LiteLLM's native bedrock_mantle/ provider) or Converse."""
    native = str(llm.model).startswith("bedrock_mantle/")
    return "mantle" if llm._mantle_delegate is not None or native else "converse"


def test_a_bedrock_fallback_takes_the_route_its_own_model_needs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bedrock picks Converse or the Mantle endpoint from the model when built,
    # so a fallback is rebuilt for its model rather than copied.
    from shipit_agent.llms import BedrockChatLLM
    from shipit_agent.llms.fallback import fallback_llms

    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key")
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
    converse = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0")
    assert _bedrock_route(converse) == "converse"
    [gemma] = fallback_llms(converse, "google.gemma-4-31b")
    assert _bedrock_route(gemma) == "mantle"
    [back] = fallback_llms(gemma, "bedrock/openai.gpt-oss-120b-1:0")
    assert _bedrock_route(back) == "converse"


def test_a_rebuilt_bedrock_adapter_keeps_the_callers_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from shipit_agent.llms import BedrockChatLLM

    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-key")
    gemma = BedrockChatLLM(model="google.gemma-4-31b", region="eu-west-1", temperature=0.2)
    converse = gemma.with_model("bedrock/openai.gpt-oss-120b-1:0")
    # The same as building it fresh with the caller's settings: nothing the
    # Mantle route consumed or rewrote carries over.
    fresh = BedrockChatLLM(model="bedrock/openai.gpt-oss-120b-1:0", region="eu-west-1", temperature=0.2)
    assert converse.completion_kwargs == fresh.completion_kwargs
    assert converse.completion_kwargs["region"] == "eu-west-1"
