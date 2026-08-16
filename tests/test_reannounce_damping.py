"""Re-announcement damping — when the model restates the same plan across steps
instead of acting, a terse 'act, don't restate' line is appended to the reminder.
The detector reads only the assistant's own narration; a first plan is never
discouraged."""

from __future__ import annotations

from shipit_agent.models import Message
from shipit_agent.prompts.reminders import (
    REANNOUNCE_DAMPER,
    build_reminder,
    is_reannouncing,
)


def _assistant(text):
    return Message(role="assistant", content=text)


def _user(text):
    return Message(role="user", content=text)


# ── the detector ──────────────────────────────────────────────────────────────


def test_single_narration_is_not_reannouncing():
    msgs = [_user("do it"), _assistant("I will check the evidence and classify the urgency.")]
    assert is_reannouncing(msgs) is False


def test_repeated_identical_plan_is_reannouncing():
    plan = "I will check the required evidence and classify the urgency now."
    msgs = [_user("go"), _assistant(plan), _user("tool result"), _assistant(plan)]
    assert is_reannouncing(msgs) is True


def test_near_identical_plan_is_reannouncing():
    msgs = [
        _user("go"),
        _assistant("I will check the required evidence and classify the urgency."),
        _user("ok"),
        _assistant("I'll check the required evidence and classify the urgency."),  # tiny variation
    ]
    assert is_reannouncing(msgs) is True


def test_distinct_narrations_are_not_reannouncing():
    msgs = [
        _user("go"),
        _assistant("First I will read the config file to find the endpoint."),
        _user("ok"),
        _assistant("Now I will run the test suite to see what fails."),
    ]
    assert is_reannouncing(msgs) is False


def test_short_blurbs_are_ignored():
    msgs = [_user("go"), _assistant("ok"), _user("x"), _assistant("ok")]
    assert is_reannouncing(msgs) is False        # too short to be a plan restatement


def test_only_assistant_text_counts_not_user_echo():
    plan = "I will fetch the records and summarise the totals for the quarter."
    msgs = [_user(plan), _assistant(plan), _user(plan)]   # user repeats don't count
    assert is_reannouncing(msgs) is False        # only one assistant narration


# ── wiring into step_request ──────────────────────────────────────────────────


class _Core:
    """Minimal object exposing step_request's dependencies."""

    max_iterations = 6
    reminder = None

    from shipit_agent.runtime_core import RuntimeCore
    step_request = RuntimeCore.step_request
    prune_stale_images = staticmethod(lambda msgs: list(msgs))


_SCHEMA = [{"type": "function", "function": {"name": "lookup", "parameters": {}}}]


def test_step_request_appends_damper_on_reannouncement():
    plan = "I will check the required evidence and classify the urgency step by step."
    messages = [_user("go"), _assistant(plan), _user("result"), _assistant(plan)]
    out_messages, _ = _Core().step_request(
        messages=messages, tool_schemas=_SCHEMA, iteration=3, ran_tools=True
    )
    tail = out_messages[-1].content
    assert REANNOUNCE_DAMPER in tail


def test_step_request_no_damper_without_repetition():
    messages = [
        _user("go"),
        _assistant("First I will read the config to find the endpoint value."),
        _user("result"),
        _assistant("Now I will run the failing test and read the traceback."),
    ]
    out_messages, _ = _Core().step_request(
        messages=messages, tool_schemas=_SCHEMA, iteration=3, ran_tools=True
    )
    tail = out_messages[-1].content
    assert REANNOUNCE_DAMPER not in tail


def test_no_damper_on_last_step():
    plan = "I will check the required evidence and classify the urgency thoroughly."
    messages = [_user("go"), _assistant(plan), _user("result"), _assistant(plan)]
    # iteration == max_iterations → last step already forces the final answer.
    out_messages, schemas = _Core().step_request(
        messages=messages, tool_schemas=_SCHEMA, iteration=6, ran_tools=True
    )
    assert schemas == []                          # last step drops tools
    assert REANNOUNCE_DAMPER not in out_messages[-1].content
