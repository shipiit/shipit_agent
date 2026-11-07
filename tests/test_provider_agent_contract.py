"""One agent task, three adapter families: the same behaviour whichever SDK answers.

Each provider is driven through a stand-in for its SDK: Anthropic's native
client, OpenAI's native client, and LiteLLM (which serves every other
provider). The task is the same everywhere: call a tool, read its result,
answer; and when the provider's first reply is a rate limit, recover.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace as NS
from typing import Any, Callable

import pytest

from shipit_agent import Agent, FunctionTool
from shipit_agent.core.policies import RetryPolicy


class RateLimitError(Exception):
    """Shaped like the SDKs' 429: a status and a response with headers."""

    def __init__(self) -> None:
        super().__init__("Error code: 429 - rate_limit_error")
        self.status_code = 429
        self.response = NS(status_code=429, headers={"retry-after": "0"})


def _weather(city: str = "") -> str:
    """Current weather for a city."""
    return f"{city}: 21C and clear"


def _script(first_reply: Any, answer: Any, *, rate_limited: bool) -> Callable[..., Any]:
    """A fake completion: optional 429, then a tool call, then the answer."""
    state = {"calls": 0, "raised": False}

    def completion(**_: Any) -> Any:
        if rate_limited and not state["raised"]:
            state["raised"] = True
            raise RateLimitError()
        state["calls"] += 1
        return first_reply if state["calls"] == 1 else answer

    return completion


def _openai_shape() -> tuple[Any, Any]:
    call = NS(
        id="call_1",
        type="function",
        function=NS(name="weather", arguments=json.dumps({"city": "Oslo"})),
    )
    tool = NS(
        choices=[
            NS(message=NS(content=None, tool_calls=[call]), finish_reason="tool_calls")
        ],
        usage=None,
    )
    done = NS(
        choices=[
            NS(
                message=NS(content="Oslo is 21C and clear.", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    return tool, done


def _anthropic_shape() -> tuple[Any, Any]:
    tool = NS(
        content=[
            NS(type="tool_use", id="toolu_1", name="weather", input={"city": "Oslo"})
        ],
        usage=None,
        stop_reason="tool_use",
    )
    done = NS(
        content=[NS(type="text", text="Oslo is 21C and clear.")],
        usage=None,
        stop_reason="end_turn",
    )
    return tool, done


def _litellm_stream_shape() -> tuple[Any, Any]:
    def chunks(delta: Any, finish: str) -> Any:
        return iter(
            [
                NS(choices=[NS(delta=delta, finish_reason=None)], usage=None),
                NS(choices=[NS(delta=None, finish_reason=finish)], usage=None),
            ]
        )

    fragment = NS(
        index=0,
        id="call_1",
        function=NS(name="weather", arguments=json.dumps({"city": "Oslo"})),
    )

    class _Replies:
        """Fresh chunk iterators each time, so a retried call can read them."""

        def __init__(self, delta: Any, finish: str) -> None:
            self.delta, self.finish = delta, finish

        def __iter__(self) -> Any:
            return chunks(self.delta, self.finish)

    tool = _Replies(NS(content=None, tool_calls=[fragment]), "tool_calls")
    done = _Replies(NS(content="Oslo is 21C and clear.", tool_calls=None), "stop")
    return tool, done


def _install(
    provider: str, monkeypatch: pytest.MonkeyPatch, *, rate_limited: bool
) -> Any:
    if provider == "anthropic":
        from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM

        create = _script(*_anthropic_shape(), rate_limited=rate_limited)
        client = NS(messages=NS(create=create), beta=NS(messages=NS(create=create)))
        monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=lambda **_: client))
        return AnthropicChatLLM(model="claude-opus-5-5", api_key="k")
    if provider == "openai":
        from shipit_agent.llms.openai_adapter import OpenAIChatLLM

        create = _script(*_openai_shape(), rate_limited=rate_limited)
        client = NS(chat=NS(completions=NS(create=create)))
        monkeypatch.setitem(sys.modules, "openai", NS(OpenAI=lambda **_: client))
        return OpenAIChatLLM(model="gpt-5.5", api_key="k")
    from shipit_agent.llms.litellm_adapter import LiteLLMChatLLM

    # The agent streams, so LiteLLM is called with stream=True and answers
    # with chunks, as the real library does.
    completion = _script(*_litellm_stream_shape(), rate_limited=rate_limited)
    monkeypatch.setitem(sys.modules, "litellm", NS(completion=completion))
    return LiteLLMChatLLM(model="mistral/mistral-large-latest")


def _agent(llm: Any) -> Agent:
    return Agent(
        llm=llm,
        tools=[FunctionTool.from_callable(_weather, name="weather")],
        retry_policy=RetryPolicy(llm_retry_base_delay=0),
    )


PROVIDERS = ["anthropic", "openai", "litellm"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_tool_call_round_trip(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _agent(_install(provider, monkeypatch, rate_limited=False)).run(
        "Weather in Oslo?"
    )

    assert [r.name for r in result.tool_results] == ["weather"]
    assert result.tool_results[0].output == "Oslo: 21C and clear"
    assert result.output == "Oslo is 21C and clear."
    assert result.metadata["run_summary"]["completion_status"] == "finished"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_rate_limit_on_the_first_call_is_recovered(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _agent(_install(provider, monkeypatch, rate_limited=True)).run(
        "Weather in Oslo?"
    )

    retries = [e for e in result.events if e.type == "llm_retry"]
    assert len(retries) == 1
    assert result.output == "Oslo is 21C and clear."
