"""A one-hour prompt cache: the request marker, the usage it reports and what it costs."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from shipit_agent.core.models import Message
from shipit_agent.core.runtime import AgentRuntime
from shipit_agent.costs.tracker import CostTracker
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.base import LLMResponse

TOOLS = [{"type": "function", "function": {"name": "a", "description": "", "parameters": {"type": "object"}}}]
HOUR = {"type": "ephemeral", "ttl": "1h"}


def _request(**options: Any) -> dict[str, Any]:
    llm = AnthropicChatLLM(model="claude-sonnet-5-5", **options)
    return llm._build_request_kwargs(
        messages=[Message(role="user", content="hi")], tools=TOOLS, system_prompt="You are helpful."
    )


def test_every_breakpoint_carries_the_hour_ttl() -> None:
    request = _request(cache_ttl="1h")
    assert request["tools"][-1]["cache_control"] == HOUR
    assert request["system"][-1]["cache_control"] == HOUR
    assert request["messages"][-1]["content"][-1]["cache_control"] == HOUR


def test_the_default_is_the_five_minute_cache_with_no_ttl_key() -> None:
    request = _request()
    assert request["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert request["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert _request(cache_ttl="5m")["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_caching_off_sends_no_marker_whatever_the_ttl() -> None:
    request = _request(prompt_caching=False, cache_ttl="1h")
    assert "cache_control" not in request["tools"][-1]
    assert request["system"] == "You are helpful."


@pytest.mark.parametrize("ttl", ["2h", "", "1H", 60])
def test_an_unknown_ttl_is_refused(ttl: Any) -> None:
    with pytest.raises(ValueError, match="cache_ttl"):
        AnthropicChatLLM(model="claude-sonnet-5-5", cache_ttl=ttl)


def _complete(monkeypatch: pytest.MonkeyPatch, usage: Any) -> LLMResponse:
    response = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="hello")], usage=usage)
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **_: types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **__: response))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    return AnthropicChatLLM(model="claude-sonnet-5-5").complete(messages=[Message(role="user", content="hi")])


def test_usage_says_how_much_was_written_for_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    usage = types.SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=300,
        cache_creation=types.SimpleNamespace(ephemeral_5m_input_tokens=100, ephemeral_1h_input_tokens=200),
    )
    out = _complete(monkeypatch, usage)
    assert out.usage["cache_creation_input_tokens"] == 300
    assert out.usage["cache_creation_1h_input_tokens"] == 200


@pytest.mark.parametrize("breakdown", [None, types.SimpleNamespace(ephemeral_1h_input_tokens=0), {"ephemeral_1h_input_tokens": None}])
def test_no_hour_writes_adds_no_key(monkeypatch: pytest.MonkeyPatch, breakdown: Any) -> None:
    usage = types.SimpleNamespace(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=300, cache_creation=breakdown
    )
    assert "cache_creation_1h_input_tokens" not in _complete(monkeypatch, usage).usage


def test_an_hour_write_costs_twice_the_input_price() -> None:
    tracker = CostTracker()
    million = 1_000_000
    # claude-sonnet-5-5: input $2, five-minute write $2.50 per million.
    five = tracker.calculate_cost("claude-sonnet-5-5", 0, 0, cache_write_tokens=million)
    hour = tracker.calculate_cost("claude-sonnet-5-5", 0, 0, cache_write_tokens=million, cache_write_1h_tokens=million)
    mixed = tracker.calculate_cost("claude-sonnet-5-5", 0, 0, cache_write_tokens=million, cache_write_1h_tokens=million // 2)
    assert (five, hour, mixed) == (2.5, 4.0, 3.25)


def test_a_models_own_hour_price_wins_and_more_hour_tokens_than_writes_are_capped() -> None:
    tracker = CostTracker()
    tracker.add_model("mine", {"input": 1.0, "output": 1.0, "cache_write": 1.0, "cache_write_1h": 3.0})
    assert tracker.calculate_cost("mine", 0, 0, cache_write_tokens=1_000_000, cache_write_1h_tokens=5_000_000) == 3.0


def test_the_tracker_records_hour_writes_from_usage() -> None:
    tracker = CostTracker()
    record = tracker.record_call("claude-sonnet-5-5", 0, 0, cache_write_tokens=1_000_000, cache_write_1h_tokens=1_000_000)
    assert record.cost_usd == 4.0


def test_a_run_prices_its_hour_writes() -> None:
    class Cached:
        model = "claude-sonnet-5-5"

        def complete(self, **_: Any) -> LLMResponse:
            return LLMResponse(
                content="done",
                usage={
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cache_creation_input_tokens": 1_000_000,
                    "cache_creation_1h_input_tokens": 1_000_000,
                },
            )

    state, _ = AgentRuntime(llm=Cached(), prompt="p").run("go")
    completed = next(event for event in state.events if event.type == "run_completed")
    assert completed.payload["usage"]["cache_creation_1h_input_tokens"] == 1_000_000
    assert completed.payload["summary"]["estimated_cost_usd"] == 4.0
