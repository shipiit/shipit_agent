"""Claude model facts, and the Anthropic adapter's request built from them.

Current Claude models reject requests older code still sends: a thinking
budget (400 on Claude 4.7 and later), forced ``tool_choice`` (400 on Opus 5.5,
Sonnet 5.5 and Fable 5.1), and a 4,096-token output cap cuts long tool calls in
half. The adapter now asks the model table instead of hard-coding one shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from shipit_agent.core.models import Message
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.claude_models import NON_STREAMING_OUTPUT_CAP, claude_model


class TestModelTable:
    @pytest.mark.parametrize(
        "model",
        [
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "claude-fable-5-1",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-haiku-5-5",
            "anthropic.claude-opus-5-5",
            "us.anthropic.claude-sonnet-5-5",
        ],
    )
    def test_current_models_think_adaptively_and_reject_budgets(
        self, model: str
    ) -> None:
        facts = claude_model(model)
        assert facts.thinking == "adaptive"
        assert facts.rejects_thinking_budget
        assert facts.max_output_tokens == 128_000
        assert facts.context_window == 1_000_000

    @pytest.mark.parametrize(
        "model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"]
    )
    def test_forced_tool_choice_is_rejected_on_the_newest_models(
        self, model: str
    ) -> None:
        assert not claude_model(model).accepts_forced_tool_choice

    @pytest.mark.parametrize(
        "model", ["claude-opus-5", "claude-sonnet-4-6", "claude-haiku-4-5"]
    )
    def test_forced_tool_choice_still_works_elsewhere(self, model: str) -> None:
        assert claude_model(model).accepts_forced_tool_choice

    def test_the_4_6_generation_still_accepts_a_budget(self) -> None:
        facts = claude_model("claude-sonnet-4-6")
        assert facts.thinking == "adaptive"
        assert not facts.rejects_thinking_budget

    def test_haiku_4_5_thinks_with_a_budget(self) -> None:
        facts = claude_model("claude-haiku-4-5")
        assert facts.thinking == "budget"
        assert facts.max_output_tokens == 64_000
        assert facts.context_window == 200_000

    def test_an_unknown_model_gets_conservative_facts(self) -> None:
        facts = claude_model("claude-something-new-9")
        assert facts.thinking == "budget"
        assert facts.max_output_tokens == 8_192
        assert facts.accepts_forced_tool_choice


def _kwargs(llm: AnthropicChatLLM, **extra: Any) -> dict[str, Any]:
    return llm._build_request_kwargs(
        messages=[Message(role="user", content="hi")],
        tools=None,
        system_prompt="s",
        **extra,
    )


class TestRequest:
    def test_max_tokens_defaults_to_the_non_streaming_cap(self) -> None:
        assert (
            _kwargs(AnthropicChatLLM(model="claude-opus-5-5"))["max_tokens"]
            == NON_STREAMING_OUTPUT_CAP
        )

    def test_max_tokens_never_exceeds_the_model(self) -> None:
        assert _kwargs(AnthropicChatLLM(model="claude-old-1"))["max_tokens"] == 8_192

    def test_an_explicit_max_tokens_wins(self) -> None:
        assert (
            _kwargs(AnthropicChatLLM(model="claude-opus-5-5", max_tokens=2_000))[
                "max_tokens"
            ]
            == 2_000
        )

    def test_no_thinking_parameter_unless_asked(self) -> None:
        assert "thinking" not in _kwargs(AnthropicChatLLM(model="claude-opus-5-5"))

    def test_adaptive_thinking_and_effort(self) -> None:
        llm = AnthropicChatLLM(
            model="claude-opus-5-5", thinking="adaptive", effort="high"
        )
        kwargs = _kwargs(llm)
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert kwargs["output_config"] == {"effort": "high"}
        assert "betas" not in kwargs

    def test_a_thinking_dict_is_sent_as_given(self) -> None:
        shape = {"type": "adaptive", "display": "summarized"}
        llm = AnthropicChatLLM(model="claude-opus-5-5", thinking=shape)
        assert _kwargs(llm)["thinking"] == shape

    def test_a_budget_becomes_adaptive_where_budgets_are_rejected(self) -> None:
        llm = AnthropicChatLLM(
            model="claude-opus-5-5",
            thinking_budget_tokens=4_096,
            interleaved_thinking=True,
        )
        kwargs = _kwargs(llm)
        assert kwargs["thinking"] == {"type": "adaptive"}
        assert "betas" not in kwargs

    def test_a_budget_is_kept_where_it_is_the_only_way_to_think(self) -> None:
        llm = AnthropicChatLLM(model="claude-haiku-4-5", thinking_budget_tokens=4_096)
        assert _kwargs(llm)["thinking"] == {"type": "enabled", "budget_tokens": 4_096}

    @pytest.mark.parametrize("bad", ["sometimes", "", 3])
    def test_an_unknown_thinking_mode_is_refused(self, bad: Any) -> None:
        with pytest.raises(ValueError):
            AnthropicChatLLM(model="claude-opus-5-5", thinking=bad)

    @pytest.mark.parametrize("bad", ["extreme", ""])
    def test_an_unknown_effort_is_refused(self, bad: str) -> None:
        with pytest.raises(ValueError):
            AnthropicChatLLM(model="claude-opus-5-5", effort=bad)


class TestRequiredToolChoice:
    def test_forced_where_accepted(self) -> None:
        llm = AnthropicChatLLM(model="claude-opus-5")
        assert llm._tool_choice_for(require_tool_call=True) == {"type": "any"}

    def test_left_to_the_model_where_forcing_is_rejected(self) -> None:
        llm = AnthropicChatLLM(model="claude-opus-5-5")
        assert llm._tool_choice_for(require_tool_call=True) is None

    def test_never_forced_unless_required(self) -> None:
        assert (
            AnthropicChatLLM(model="claude-opus-5")._tool_choice_for(
                require_tool_call=False
            )
            is None
        )
