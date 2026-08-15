"""HITL tool confirmation — the @requires_confirmation decorator and its
first-class integration with the permission gate. A decorated tool asks a human
before it runs, even under a bypass/allow mode; a hard deny still outranks it;
and a `when` predicate makes confirmation conditional on the call's arguments.
"""

from __future__ import annotations

import pytest

from shipit_agent.permissions import PermissionDecision, PermissionEngine
from shipit_agent.tools.confirmation import (
    ToolConfirmation,
    confirmation_spec,
    needs_confirmation,
    requires_confirmation,
)


# ── the decorator, all call styles ────────────────────────────────────────


def test_bare_decorator_marks_a_tool():
    @requires_confirmation
    class T:
        name = "t"

    assert needs_confirmation(T)
    assert confirmation_spec(T).message == ""


def test_positional_message():
    @requires_confirmation("Deletes files.")
    class T:
        name = "delete"

    assert confirmation_spec(T).message == "Deletes files."


def test_keyword_message_impact_and_when():
    @requires_confirmation(message="Big transfer.", impact="irreversible",
                           when=lambda a: a.get("amount", 0) >= 10_000)
    def wire_transfer(amount, to):
        return "sent"

    spec = confirmation_spec(wire_transfer)
    assert spec.message == "Big transfer." and spec.impact == "irreversible"
    assert spec.applies({"amount": 50_000}) is True
    assert spec.applies({"amount": 5}) is False


def test_invalid_impact_falls_back():
    @requires_confirmation("x", impact="apocalyptic")
    class T:
        name = "t"

    assert confirmation_spec(T).impact == "default"


def test_undecorated_tool_needs_no_confirmation():
    class Plain:
        name = "plain"

    assert confirmation_spec(Plain) is None
    assert needs_confirmation(Plain) is False


def test_bare_boolean_flag_is_honoured():
    # A hand-set `requires_confirmation = True` (no decorator) still gates.
    class T:
        name = "t"
        requires_confirmation = True

    assert needs_confirmation(T)


def test_needs_confirmation_evaluates_when():
    @requires_confirmation(when=lambda a: a["danger"])
    def f(danger):
        return "ok"

    assert needs_confirmation(f, {"danger": True}) is True
    assert needs_confirmation(f, {"danger": False}) is False


def test_broken_predicate_fails_safe_and_asks():
    def boom(_args):
        raise RuntimeError("predicate blew up")

    spec = ToolConfirmation(when=boom)
    assert spec.applies({}) is True  # a broken gate must still ask, never skip


# ── integration with the permission gate ──────────────────────────────────


def _tool(**attrs):
    return type("Tool", (), {"name": "act", **attrs})


def test_gate_asks_for_a_confirmed_tool_even_in_bypass():
    @requires_confirmation("Careful.")
    class Danger:
        name = "danger"

    policy = PermissionEngine(mode="bypass")   # bypass would allow everything…
    result = policy.check("danger", {}, tool=Danger)
    assert result.decision == PermissionDecision.ASK  # …but the tool floors it
    assert "Careful." in result.reason


def test_gate_hard_deny_outranks_confirmation():
    @requires_confirmation("Careful.")
    class Danger:
        name = "danger"

    policy = PermissionEngine(deny=["danger"])
    result = policy.check("danger", {}, tool=Danger)
    assert result.decision == PermissionDecision.DENY


def test_gate_conditional_confirmation_only_asks_when_predicate_true():
    @requires_confirmation("Big transfer.", when=lambda a: a.get("amount", 0) >= 10_000)
    class Wire:
        name = "wire"

    policy = PermissionEngine(mode="bypass")
    assert policy.check("wire", {"amount": 5}, tool=Wire).decision == PermissionDecision.ALLOW
    assert policy.check("wire", {"amount": 99_999}, tool=Wire).decision == PermissionDecision.ASK


def test_gate_undecorated_tool_is_unaffected():
    policy = PermissionEngine(mode="bypass")
    assert policy.check("plain", {}, tool=_tool()).decision == PermissionDecision.ALLOW


def test_gate_uses_the_ask_callback_when_present():
    from shipit_agent.permissions import PermissionResult

    @requires_confirmation("Careful.")
    class Danger:
        name = "danger"

    seen = {}

    def approve(name, args):
        seen["asked"] = name
        return PermissionResult(PermissionDecision.ALLOW, reason="human said yes")

    policy = PermissionEngine(mode="bypass", callback=approve)
    result = policy.check("danger", {}, tool=Danger)
    assert seen["asked"] == "danger"
    assert result.decision == PermissionDecision.ALLOW
