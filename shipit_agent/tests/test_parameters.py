"""Parameter canonicalisation, coercion, wire/host routing, and Agent knobs."""

from __future__ import annotations

import pytest

from shipit_agent.llms.parameters import (
    HOST_PARAMS,
    WIRE_PARAMS,
    canonical_name,
    coerce_numeric,
    normalize_parameters,
    resolve_parameters,
)
from shipit_agent.graph import AgentGraph
from shipit_agent.tests.test_bridge import LegacyAgent
from shipit_agent.tests.test_graph import Reply, ScriptedLLM
from shipit_agent.bridge import spec_from_agent

GEMMA = "google.gemma-4-31b"


# --------------------------------------------------------------------------- #
# Canonical spelling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "given,expected",
    [
        ("topP", "top_p"),
        ("top_p", "top_p"),
        ("topK", "top_k"),
        ("maxTokens", "max_tokens"),
        ("maxOutputTokens", "max_output_tokens"),
        ("maxContextTokens", "max_context_tokens"),
        ("frequencyPenalty", "frequency_penalty"),
        ("presencePenalty", "presence_penalty"),
        ("thinkingBudget", "thinking_budget"),
        ("fileTokenLimit", "file_token_limit"),
        ("temperature", "temperature"),
    ],
)
def test_both_spellings_resolve_to_one_setting(given, expected):
    assert canonical_name(given) == expected


def test_an_unknown_name_is_left_alone():
    assert canonical_name("some_future_knob") == "some_future_knob"


# --------------------------------------------------------------------------- #
# Coercion
# --------------------------------------------------------------------------- #


def test_a_string_from_a_form_becomes_a_number():
    clean, rejected = normalize_parameters({"temperature": "0.7", "max_tokens": "512"})
    assert clean == {"temperature": 0.7, "max_tokens": 512}
    assert rejected == {}


def test_explicit_zero_survives():
    """`temperature=0` is a deliberate choice, not a missing value."""
    clean, _ = normalize_parameters({"temperature": 0})
    assert clean["temperature"] == 0


def test_negative_values_survive():
    clean, _ = normalize_parameters({"presence_penalty": -0.5})
    assert clean["presence_penalty"] == -0.5


def test_a_boolean_where_a_float_belongs_is_rejected_not_silently_cast():
    clean, rejected = normalize_parameters({"temperature": True})
    assert "temperature" not in clean
    assert "temperature" in rejected


@pytest.mark.parametrize("value", ["", "  ", "hot", None, float("nan"), float("inf")])
def test_values_that_cannot_be_numbers_do_not_reach_the_provider(value):
    clean, _ = normalize_parameters({"temperature": value})
    assert "temperature" not in clean


def test_a_placeholder_string_is_reported_rather_than_absorbed():
    _, rejected = normalize_parameters({"top_p": "{{value}}"})
    assert rejected == {"top_p": "{{value}}"}


def test_non_numeric_parameters_pass_through_untouched():
    clean, _ = normalize_parameters({"stop": ["\n\n"], "response_format": {"type": "json"}})
    assert clean["stop"] == ["\n\n"]


# --------------------------------------------------------------------------- #
# Wire vs host routing — the bug this fixes
# --------------------------------------------------------------------------- #


def test_host_parameters_never_reach_the_provider():
    """max_context_tokens tells the compactor when to act. It is not a wire field."""
    resolved = resolve_parameters(GEMMA, {"temperature": 0.5, "max_context_tokens": 100_000})
    assert "max_context_tokens" not in resolved.wire
    assert resolved.host["max_context_tokens"] == 100_000


def test_file_token_limit_is_also_host_side():
    resolved = resolve_parameters(GEMMA, {"fileTokenLimit": 4000})
    assert "file_token_limit" not in resolved.wire
    assert resolved.host["file_token_limit"] == 4000


def test_the_two_tables_do_not_overlap():
    assert not (WIRE_PARAMS & HOST_PARAMS)


def test_every_key_the_old_table_listed_is_classified():
    legacy = [
        "temperature", "top_p", "topP", "top_k", "topK",
        "frequency_penalty", "frequencyPenalty",
        "presence_penalty", "presencePenalty",
        "max_tokens", "maxTokens",
        "max_output_tokens", "maxOutputTokens",
        "max_context_tokens", "maxContextTokens",
        "fileTokenLimit", "thinking_budget", "thinkingBudget",
    ]
    for name in legacy:
        canonical = canonical_name(name)
        assert canonical in WIRE_PARAMS or canonical in HOST_PARAMS, canonical


def test_an_unrecognised_parameter_is_forwarded_not_dropped():
    """A provider may accept a field this package has never heard of."""
    resolved = resolve_parameters("unknown-model", {"future_knob": 1})
    assert resolved.wire["future_knob"] == 1
    assert "future_knob" in resolved.unknown


# --------------------------------------------------------------------------- #
# Family adaptation
# --------------------------------------------------------------------------- #


def test_gemma_receives_only_what_mantle_accepts():
    resolved = resolve_parameters(
        GEMMA,
        {
            "temperature": 0.7,
            "top_p": 0.9,
            "topK": 40,
            "frequency_penalty": 0.2,
            "presencePenalty": 0.1,
            "thinkingBudget": 2048,
            "n": 2,
        },
    )
    assert set(resolved.wire) == {"temperature", "top_p"}
    assert set(resolved.dropped) == {
        "top_k", "frequency_penalty", "presence_penalty", "thinking_budget", "n"
    }


def test_recommendations_fill_only_what_the_caller_left_unset():
    resolved = resolve_parameters(GEMMA, {"temperature": 0.2})
    assert resolved.wire["temperature"] == 0.2
    assert resolved.wire["top_p"] == 0.95
    assert resolved.recommended == {"top_p": 0.95}


def test_recommendations_can_be_switched_off():
    resolved = resolve_parameters(GEMMA, {"temperature": 0.2}, apply_recommendations=False)
    assert "top_p" not in resolved.wire


def test_an_unknown_model_is_never_degraded():
    params = {"temperature": 0.3, "top_k": 40, "frequency_penalty": 0.1}
    resolved = resolve_parameters("some-future-model", params)
    assert resolved.wire == params
    assert resolved.dropped == {}


def test_openai_reasoning_models_get_the_renamed_token_limit():
    resolved = resolve_parameters("gpt-5", {"max_tokens": 500, "temperature": 0.5})
    assert resolved.wire["max_completion_tokens"] == 500
    assert "temperature" in resolved.dropped


def test_explain_names_every_decision():
    text = resolve_parameters(
        GEMMA, {"temperature": 0.5, "topK": 40, "maxContextTokens": 1000, "top_p": "x"}
    ).explain()
    assert "sent:" in text
    assert "used locally:" in text
    assert "blocked for this model:" in text
    assert "not numeric, ignored:" in text


# --------------------------------------------------------------------------- #
# Through the bridge
# --------------------------------------------------------------------------- #


def _run(llm, **agent_fields):
    agent = LegacyAgent(llm=llm, model=GEMMA, **agent_fields)
    list(AgentGraph(spec_from_agent(agent)).run("hi"))
    return llm.calls[0]


def test_parameters_reach_the_model_through_the_bridge():
    sent = _run(
        ScriptedLLM(Reply(content="ok")),
        model_parameters={"temperature": 0.2, "max_tokens": 256},
    )
    assert sent["temperature"] == 0.2
    assert sent["max_tokens"] == 256


def test_a_zero_is_passed_through_not_treated_as_unset():
    assert _run(ScriptedLLM(Reply(content="ok")), model_parameters={"temperature": 0})[
        "temperature"
    ] == 0


def test_camel_case_from_a_config_file_still_works():
    sent = _run(
        ScriptedLLM(Reply(content="ok")),
        model_parameters={"topP": 0.8, "maxTokens": "128"},
    )
    assert sent["top_p"] == 0.8
    assert sent["max_tokens"] == 128


def test_max_context_tokens_does_not_reach_the_model():
    sent = _run(ScriptedLLM(Reply(content="ok")), model_parameters={"max_context_tokens": 64_000})
    assert "max_context_tokens" not in sent


def test_host_parameters_change_the_loop_not_the_request():
    sent = _run(
        ScriptedLLM(*[Reply(content="ok") for _ in range(5)]),
        model_parameters={"max_iterations": 3},
    )
    assert "max_iterations" not in sent


def test_the_run_summary_records_the_parameter_decisions():
    agent = LegacyAgent(llm=ScriptedLLM(Reply(content="ok")), model=GEMMA,
                        model_parameters={"temperature": 0.3, "top_k": 40})
    events = list(AgentGraph(spec_from_agent(agent)).run("hi"))
    summary = next(e for e in events if e.type == "run_summary")
    assert "temperature" in summary.payload["parameters"]
    assert "top_k" in summary.payload["parameters"]
