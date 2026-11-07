"""Permission decisions in the Claude Agent SDK's order.

hooks, then deny rules, then ask rules, then the mode, then allow rules,
then the callback. An ask rule is a request for a human: neither bypass
mode nor a broad allow pattern may silently override it. ``dontAsk`` refuses
anything not pre-approved instead of asking.
"""

from __future__ import annotations

import pytest

from shipit_agent.safety.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionResult,
    coerce_permissions,
)


def _decide(engine: PermissionEngine, tool: str = "deploy") -> PermissionDecision:
    return engine.check(tool, {}).decision


def test_deny_beats_everything() -> None:
    engine = PermissionEngine(
        mode="bypass", deny=["deploy"], allow=["*"], ask=["deploy"]
    )
    assert _decide(engine) is PermissionDecision.DENY


def test_an_ask_rule_holds_in_bypass_mode() -> None:
    assert (
        _decide(PermissionEngine(mode="bypass", ask=["deploy"]))
        is PermissionDecision.ASK
    )


def test_an_ask_rule_beats_a_broad_allow() -> None:
    assert (
        _decide(PermissionEngine(allow=["*"], ask=["deploy"])) is PermissionDecision.ASK
    )


def test_an_ask_rule_still_lets_the_callback_answer() -> None:
    engine = PermissionEngine(
        ask=["deploy"],
        callback=lambda name, args: PermissionResult(
            PermissionDecision.ALLOW, reason="approved"
        ),
    )
    assert _decide(engine) is PermissionDecision.ALLOW


def test_bypass_allows_what_no_rule_mentions() -> None:
    assert (
        _decide(PermissionEngine(mode="bypass"), "anything") is PermissionDecision.ALLOW
    )


class TestDontAsk:
    def test_an_allowed_tool_runs(self) -> None:
        assert (
            _decide(PermissionEngine(mode="dontAsk", allow=["deploy"]))
            is PermissionDecision.ALLOW
        )

    def test_anything_else_is_refused_not_asked(self) -> None:
        result = PermissionEngine(mode="dontAsk").check("deploy", {})
        assert result.decision is PermissionDecision.DENY
        assert "pre-approved" in result.reason

    def test_an_ask_rule_becomes_a_refusal(self) -> None:
        assert (
            _decide(PermissionEngine(mode="dontAsk", ask=["deploy"]))
            is PermissionDecision.DENY
        )

    def test_the_callback_can_still_approve(self) -> None:
        engine = PermissionEngine(
            mode="dontAsk",
            callback=lambda name, args: PermissionResult(PermissionDecision.ALLOW),
        )
        assert _decide(engine) is PermissionDecision.ALLOW

    def test_risky_calls_are_refused_too(self) -> None:
        result = PermissionEngine(mode="dontAsk", allow=["bash"]).check(
            "bash", {}, risk=("it deletes files",)
        )
        assert result.decision is PermissionDecision.ALLOW
        unlisted = PermissionEngine(mode="dontAsk").check(
            "bash", {}, risk=("it deletes files",)
        )
        assert unlisted.decision is PermissionDecision.DENY


@pytest.mark.parametrize("spelling", ["bypassPermissions", "bypass"])
def test_the_sdk_spelling_of_bypass_is_accepted(spelling: str) -> None:
    engine = coerce_permissions(spelling)
    assert engine is not None and engine.mode == "bypass"


def test_dont_ask_is_accepted_by_name() -> None:
    engine = coerce_permissions("dontAsk")
    assert engine is not None and engine.mode == "dontAsk"
