"""Per-model parameter sanitizing.

Each case here stands for an HTTP 400 on a live turn. The parameters involved
usually arrive from defaults rather than intent, so the error names a field the
caller never chose — and the same code works on the next model, which makes it
read as "this model is broken" instead of "this parameter is unsupported".
"""

from __future__ import annotations

import pytest

from shipit_agent.llms.capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    capabilities_for,
    register_rule,
    sanitize_params,
    supports,
)


class TestGoogle:
    def test_gemini_3_5_flash_rejects_sampling_and_budget(self) -> None:
        kept, dropped = sanitize_params(
            "gemini-3.5-flash",
            {"temperature": 0.7, "top_p": 0.9, "thinking_budget": 1024, "max_tokens": 8},
        )
        assert set(dropped) == {"temperature", "top_p", "thinking_budget"}
        assert kept == {"max_tokens": 8}

    def test_older_gemini_is_untouched(self) -> None:
        """The rule must not reach backwards — 2.5 accepts these."""
        kept, dropped = sanitize_params("gemini-2.5-pro", {"temperature": 0.7})
        assert dropped == {} and kept == {"temperature": 0.7}

    def test_camel_and_snake_spellings_are_both_caught(self) -> None:
        """Different SDKs spell it differently; catching one is catching none."""
        _, dropped = sanitize_params(
            "gemini-3.5-flash", {"topP": 0.9, "top_p": 0.9, "thinkingBudget": 5}
        )
        assert set(dropped) == {"topP", "top_p", "thinkingBudget"}


class TestOpenAIReasoning:
    @pytest.mark.parametrize("model", ["o1", "o3-mini", "gpt-5", "gpt-5-mini"])
    def test_reasoning_models_drop_sampling(self, model) -> None:
        _, dropped = sanitize_params(model, {"temperature": 0.7})
        assert "temperature" in dropped

    @pytest.mark.parametrize("model", ["gpt-5-chat", "gpt-5.1", "gpt-4o"])
    def test_non_reasoning_variants_keep_sampling(self, model) -> None:
        """The negative lookahead is load-bearing: without it every GPT-5
        variant is stripped and the chat ones silently lose their temperature."""
        kept, dropped = sanitize_params(model, {"temperature": 0.7})
        assert dropped == {} and kept == {"temperature": 0.7}

    def test_max_tokens_is_renamed_not_dropped(self) -> None:
        kept, dropped = sanitize_params("o3-mini", {"max_tokens": 100})
        assert kept == {"max_completion_tokens": 100}
        assert dropped == {}


class TestBedrockFamilies:
    def test_non_anthropic_bedrock_drops_modify_params(self) -> None:
        _, dropped = sanitize_params(
            "bedrock/amazon.nova-pro-v1:0", {"modify_params": True}
        )
        assert "modify_params" in dropped

    def test_anthropic_on_bedrock_keeps_it(self) -> None:
        kept, _ = sanitize_params(
            "bedrock/anthropic.claude-sonnet-4-v1:0", {"modify_params": True}
        )
        assert kept == {"modify_params": True}


class TestPermissiveByDefault:
    def test_unknown_model_blocks_nothing(self) -> None:
        params = {"temperature": 0.7, "wild_vendor_param": 1}
        kept, dropped = sanitize_params("some-brand-new-model", params)
        assert kept == params and dropped == {}

    def test_no_model_and_no_params_are_safe(self) -> None:
        assert sanitize_params(None, {"temperature": 1}) == ({"temperature": 1}, {})
        assert sanitize_params("gpt-5", {}) == ({}, {})

    def test_capabilities_for_unmatched_is_the_default_object(self) -> None:
        assert capabilities_for("nothing-matches-this") is DEFAULT_CAPABILITIES


class TestCapabilityQueries:
    @pytest.mark.parametrize(
        "model,capability,expected",
        [
            ("claude-sonnet-4", "supports_prompt_cache", True),
            ("gpt-4o", "supports_prompt_cache", False),
            ("gemini-3.5-flash", "supports_reasoning", True),
            ("claude-sonnet-4", "supports_tools", True),
        ],
    )
    def test_supports(self, model, capability, expected) -> None:
        assert supports(model, capability) is expected

    def test_unknown_capability_name_is_false_not_an_error(self) -> None:
        assert supports("gpt-4o", "supports_telepathy") is False


class TestExtensibility:
    def test_a_registered_rule_wins_over_a_shipped_one(self) -> None:
        from shipit_agent.llms import capabilities as caps_mod

        original = list(caps_mod.RULES)
        try:
            register_rule(
                r"gpt-5-special",
                ModelCapabilities(blocked_params=frozenset({"seed"}), reason="test"),
            )
            kept, dropped = sanitize_params("gpt-5-special", {"seed": 1, "temperature": 1})
            assert "seed" in dropped
            # The shipped GPT-5 rule would have dropped temperature; ours wins.
            assert kept == {"temperature": 1}
        finally:
            caps_mod.RULES[:] = original
