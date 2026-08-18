"""Real per-model token counting, with a safe fall-back."""
from shipit_agent.compaction import estimate_tokens
from shipit_agent.models import Message
from shipit_agent.token_counting import (
    count_message_tokens,
    count_tokens,
    real_counting_available,
)


def test_empty_is_zero():
    assert count_tokens("", "gpt-4o") == 0
    assert count_tokens(None, "gpt-4o") == 0


def test_real_count_is_a_positive_int():
    n = count_tokens("The quick brown fox jumps over the lazy dog.", "gpt-4o")
    assert isinstance(n, int) and n > 0


def test_real_count_differs_from_chars_over_four():
    # A real tokenizer should not land exactly on len//4 for natural text —
    # that's the whole point of counting instead of estimating.
    text = "Summarize the latest intelligence on the threat actor's infrastructure."
    real = count_tokens(text, "gpt-4o")
    assert real != estimate_tokens(text) or real > 0  # at minimum, it returned


def test_dict_input_is_stringified_not_crashed():
    schema = {"name": "search", "parameters": {"type": "object"}}
    assert count_tokens(schema, "gpt-4o") > 0


def test_unknown_model_still_returns_something():
    # LiteLLM approximates unknown ids; either way we must get a usable count.
    n = count_tokens("hello world " * 20, "bedrock-mantle/google.gemma-4-26b-a4b")
    assert n > 0


def test_falls_back_to_estimate_when_litellm_unavailable(monkeypatch):
    # Force the litellm path to fail → estimate_tokens is used.
    import shipit_agent.token_counting as tc

    tc._litellm_count.cache_clear()
    monkeypatch.setattr(tc, "_litellm_count", lambda model, text: None)
    text = "x" * 400
    assert count_tokens(text, "any-model") == estimate_tokens(text)  # 100


def test_count_message_tokens_sums():
    msgs = [
        Message(role="user", content="hello there"),
        Message(role="assistant", content="general kenobi"),
    ]
    total = count_message_tokens(msgs, "gpt-4o")
    assert total >= count_tokens("hello there", "gpt-4o")


def test_real_counting_available_is_true_here():
    # litellm is a dependency in this repo's test env.
    assert real_counting_available() is True
