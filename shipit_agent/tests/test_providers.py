"""Capabilities, wire-format adaptation, Mantle auth, and throttle taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from shipit_agent.llms.capabilities import (
    apply_recommended_params,
    capabilities_for,
    describe,
    sanitize_params,
)
from shipit_agent.llms.mantle import (
    MantleAuthError,
    MantleRegionError,
    RefreshingBearerToken,
    check_region,
    iam_hint,
    mantle_base_url,
)
from shipit_agent.llms.throttle import (
    DEFAULT_SCHEDULE,
    BackoffPolicy,
    ThrottleKind,
    classify,
)
from shipit_agent.llms.wire import (
    UnsupportedImageSource,
    apply_reasoning_policy,
    normalize_content,
    strip_reasoning,
)


@dataclass(slots=True)
class Msg:
    """Stands in for the host's Message; same constructor shape."""

    role: str
    content: Any
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Capabilities
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "model",
    ["google.gemma-4-31b", "bedrock_mantle/google.gemma-4-26b-a4b", "gemma4-31b"],
)
def test_gemma_family_is_matched_in_every_spelling(model):
    caps = capabilities_for(model)
    assert caps.schema_dialect == "openai_strict"
    assert caps.reasoning_history == "strip"
    assert caps.prompt_cache_mode == "implicit"


def test_e2b_rule_precedes_the_family_rule():
    caps = capabilities_for("google.gemma-4-e2b")
    assert caps.default_reasoning_effort == "high"
    assert caps.context_window == 128_000
    assert capabilities_for("google.gemma-4-31b").context_window == 256_000


def test_gemma_blocks_unsupported_sampling_in_both_spellings():
    accepted, dropped = sanitize_params(
        "google.gemma-4-31b",
        {"temperature": 0.7, "top_p": 0.9, "topK": 40, "frequency_penalty": 0.1, "n": 2},
    )
    assert set(accepted) == {"temperature", "top_p"}
    assert set(dropped) == {"topK", "frequency_penalty", "n"}


def test_recommendations_fill_gaps_without_overriding_intent():
    filled = apply_recommended_params("google.gemma-4-31b", {"temperature": 0.0})
    assert filled["temperature"] == 0.0  # explicit zero survives
    assert filled["top_p"] == 0.95


def test_recommendations_never_reintroduce_a_blocked_param():
    caps = capabilities_for("google.gemma-4-31b")
    assert not set(caps.recommended_params) & caps.blocked_params


def test_deepseek_replays_reasoning_and_gemma_strips_it():
    assert capabilities_for("deepseek-chat").reasoning_history == "replay"
    assert capabilities_for("google.gemma-4-31b").reasoning_history == "strip"


def test_gpt5_chat_keeps_sampling_but_gpt5_does_not():
    accepted, _ = sanitize_params("gpt-5-chat", {"temperature": 0.5})
    assert accepted == {"temperature": 0.5}
    accepted, dropped = sanitize_params("gpt-5", {"temperature": 0.5})
    assert accepted == {} and "temperature" in dropped


def test_unknown_model_is_left_completely_alone():
    params = {"temperature": 0.3, "wildcard": 1}
    accepted, dropped = sanitize_params("some-future-model-v9", params)
    assert accepted == params and dropped == {}


def test_input_budget_reserves_output_room():
    assert capabilities_for("google.gemma-4-31b").input_budget() == 256_000 - 16_384
    assert capabilities_for("unknown").input_budget() is None


def test_describe_renders_a_matrix_row_per_model():
    rows = describe(["google.gemma-4-31b", "claude-sonnet-4"])
    assert [r["model"] for r in rows] == ["google.gemma-4-31b", "claude-sonnet-4"]
    assert rows[0]["schema_dialect"] == "openai_strict"


# --------------------------------------------------------------------------- #
# Wire format
# --------------------------------------------------------------------------- #


def test_https_image_is_inlined_when_a_fetcher_is_available():
    def fetch(url: str) -> tuple[bytes, str]:
        return b"\x89PNG", "image/png"

    content = [
        {"type": "text", "text": "describe"},
        {"type": "image_url", "image_url": {"url": "https://example.com/c.png"}},
    ]
    result = normalize_content(content, model="google.gemma-4-31b", fetcher=fetch)
    assert result[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result[1]["type"] == "text"  # and images moved first


def test_unsupported_image_without_a_fetcher_becomes_an_honest_note():
    content = [{"type": "image_url", "image_url": {"url": "https://example.com/c.png"}}]
    result = normalize_content(content, model="google.gemma-4-31b")
    assert result[0]["type"] == "text"
    assert "image omitted" in result[0]["text"]


def test_strict_mode_raises_rather_than_degrading():
    content = [{"type": "image_url", "image_url": {"url": "https://example.com/c.png"}}]
    with pytest.raises(UnsupportedImageSource):
        normalize_content(content, model="google.gemma-4-31b", strict=True)


def test_s3_urls_pass_through_for_gemma():
    content = [{"type": "image_url", "image_url": {"url": "s3://bucket/c.png"}}]
    assert normalize_content(content, model="google.gemma-4-31b") == content


def test_block_reordering_is_stable_within_each_class():
    content = [
        {"type": "text", "text": "one"},
        {"type": "text", "text": "two"},
        {"type": "image_url", "image_url": {"url": "s3://b/a.png"}},
    ]
    result = normalize_content(content, model="google.gemma-4-31b")
    assert [b.get("text") for b in result if b["type"] == "text"] == ["one", "two"]
    assert result[0]["type"] == "image_url"


def test_plain_string_content_is_untouched():
    assert normalize_content("hello", model="google.gemma-4-31b") == "hello"


def test_reasoning_is_stripped_for_gemma_and_replayed_for_deepseek():
    history = [Msg("assistant", "answer", metadata={"reasoning_content": "secret"})]
    stripped = apply_reasoning_policy(history, model="google.gemma-4-31b")
    assert "reasoning_content" not in stripped[0].metadata
    replayed = apply_reasoning_policy(history, model="deepseek-chat")
    assert replayed[0].metadata["reasoning_content"] == "secret"


def test_strip_reasoning_leaves_other_metadata_and_the_original_intact():
    original = Msg("assistant", "a", metadata={"reasoning": "x", "tool_call_id": "t1"})
    cleaned = strip_reasoning(original)
    assert cleaned.metadata == {"tool_call_id": "t1"}
    assert original.metadata["reasoning"] == "x"


def test_strip_reasoning_returns_the_same_object_when_nothing_to_do():
    message = Msg("user", "hi", metadata={"k": "v"})
    assert strip_reasoning(message) is message


# --------------------------------------------------------------------------- #
# Mantle
# --------------------------------------------------------------------------- #


def test_supported_region_builds_the_openai_compatible_url():
    assert (
        mantle_base_url("us-east-1")
        == "https://bedrock-mantle.us-east-1.api.aws/openai/v1"
    )


def test_unsupported_region_fails_before_any_call_and_names_alternatives():
    with pytest.raises(MantleRegionError) as excinfo:
        check_region("eu-west-1")
    message = str(excinfo.value)
    assert "eu-central-1" in message and "Nearest alternative" in message


def test_missing_region_is_its_own_message():
    with pytest.raises(MantleRegionError, match="No AWS region"):
        check_region(None)


def test_iam_hint_names_the_managed_policy_and_actions():
    hint = iam_hint(403)
    assert "AmazonBedrockMantleInferenceAccess" in hint
    assert "bedrock-mantle:CreateInference" in hint


def test_token_is_derived_once_and_reused_until_the_refresh_point():
    calls = []
    now = [0.0]

    def generate(**_: Any) -> str:
        calls.append(1)
        return f"token-{len(calls)}"

    token = RefreshingBearerToken(
        generate, region="us-east-1", ttl_seconds=100, refresh_at=0.8,
        clock=lambda: now[0],
    )
    assert token.get() == "token-1"
    now[0] = 79
    assert token.get() == "token-1"
    now[0] = 81
    assert token.get() == "token-2"
    assert len(calls) == 2


def test_force_refresh_derives_immediately():
    counter = iter(["a", "b"])
    token = RefreshingBearerToken(lambda **_: next(counter), region="us-east-1")
    assert token.get() == "a"
    assert token.force_refresh() == "b"


def test_generator_failure_explains_both_ways_to_fix_it():
    def boom(**_: Any) -> str:
        raise RuntimeError("no credentials")

    token = RefreshingBearerToken(boom, region="us-east-1")
    with pytest.raises(MantleAuthError) as excinfo:
        token.get()
    assert "AWS_BEARER_TOKEN_BEDROCK" in str(excinfo.value)


def test_token_is_usable_as_a_plain_callable():
    token = RefreshingBearerToken(lambda **_: "t", region="us-east-1")
    assert token() == "t"


# --------------------------------------------------------------------------- #
# Throttling
# --------------------------------------------------------------------------- #


class _HttpError(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message or str(status))
        self.status_code = status


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, ThrottleKind.TOKEN_QUOTA),
        (503, ThrottleKind.CAPACITY),
        (401, ThrottleKind.AUTH),
        (403, ThrottleKind.AUTH),
        (400, ThrottleKind.BAD_REQUEST),
        (500, ThrottleKind.TRANSIENT),
    ],
)
def test_status_codes_classify_to_distinct_actions(status, expected):
    assert classify(_HttpError(status)) is expected


def test_message_fallback_when_no_status_is_exposed():
    assert classify(Exception("Too Many Requests")) is ThrottleKind.TOKEN_QUOTA
    assert classify(Exception("Service Unavailable")) is ThrottleKind.CAPACITY


def test_bad_request_is_never_retried_and_auth_refreshes_first():
    assert not ThrottleKind.BAD_REQUEST.retryable
    assert not DEFAULT_SCHEDULE.should_retry(ThrottleKind.BAD_REQUEST, attempt=0)
    assert DEFAULT_SCHEDULE.policy_for(ThrottleKind.AUTH).refresh_credentials_first


def test_token_quota_backs_off_harder_than_capacity():
    quota = DEFAULT_SCHEDULE.policy_for(ThrottleKind.TOKEN_QUOTA)
    capacity = DEFAULT_SCHEDULE.policy_for(ThrottleKind.CAPACITY)
    assert quota.base_delay > capacity.base_delay


def test_jitter_stays_within_the_computed_ceiling():
    policy = BackoffPolicy(base_delay=4.0, multiplier=2.0, max_delay=100.0)
    delays = [policy.delay_for(3) for _ in range(200)]
    assert all(0.0 <= d <= 16.0 for d in delays)
    assert len(set(delays)) > 1  # actually jittered


def test_unclassified_errors_are_retryable_but_conservative():
    kind = classify(Exception("something odd"))
    assert kind is ThrottleKind.UNKNOWN
    assert DEFAULT_SCHEDULE.policy_for(kind).max_attempts == 2
