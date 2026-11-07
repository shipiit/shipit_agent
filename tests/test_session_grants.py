"""Approving a call for the session, so the same call does not ask again.

Like Claude Code's "don't ask again": a callback returns ALLOW with
scope="session" and that exact call (tool and arguments) is approved for
the rest of the agent's session. A different call still asks; deny rules
still win.
"""

from __future__ import annotations

from typing import Any

from shipit_agent.safety.permissions import (
    PermissionDecision,
    PermissionEngine,
    PermissionResult,
)


def _engine(scope: str, asked: list[dict[str, Any]], **rules: Any) -> PermissionEngine:
    def callback(name: str, arguments: dict[str, Any]) -> PermissionResult:
        asked.append(arguments)
        return PermissionResult(PermissionDecision.ALLOW, scope=scope)

    return PermissionEngine(ask=["bash"], callback=callback, **rules)


def test_a_session_grant_stops_the_same_call_from_asking_again() -> None:
    asked: list[dict[str, Any]] = []
    engine = _engine("session", asked)
    first = engine.check("bash", {"command": "rm build.log"})
    second = engine.check("bash", {"command": "rm build.log"})
    assert first.allowed and second.allowed
    assert asked == [{"command": "rm build.log"}]
    assert "session" in second.reason


def test_a_different_call_still_asks() -> None:
    asked: list[dict[str, Any]] = []
    engine = _engine("session", asked)
    engine.check("bash", {"command": "rm build.log"})
    engine.check("bash", {"command": "rm -rf src"})
    assert len(asked) == 2


def test_approve_once_asks_every_time() -> None:
    asked: list[dict[str, Any]] = []
    engine = _engine("once", asked)
    engine.check("bash", {"command": "rm build.log"})
    engine.check("bash", {"command": "rm build.log"})
    assert len(asked) == 2


def test_a_deny_rule_beats_a_session_grant() -> None:
    asked: list[dict[str, Any]] = []
    engine = _engine("session", asked)
    engine.check("bash", {"command": "rm build.log"})
    engine.deny.append("bash")
    assert engine.check("bash", {"command": "rm build.log"}).denied


def test_risky_shell_commands_can_be_granted_for_the_session() -> None:
    asked: list[dict[str, Any]] = []

    def callback(name: str, arguments: dict[str, Any]) -> PermissionResult:
        asked.append(arguments)
        return PermissionResult(PermissionDecision.ALLOW, scope="session")

    engine = PermissionEngine(callback=callback)
    risk = ("it deletes files",)
    engine.check("bash", {"command": "rm a"}, risk=risk)
    assert engine.check("bash", {"command": "rm a"}, risk=risk).allowed
    assert len(asked) == 1


def test_the_agent_keeps_its_grants_across_runs() -> None:
    from shipit_agent import Agent
    from shipit_agent.llms import SimpleEchoLLM

    agent = Agent(
        llm=SimpleEchoLLM(),
        permission_callback=lambda name, arguments: PermissionResult(
            PermissionDecision.ALLOW, scope="session"
        ),
    )
    assert agent._effective_permissions() is agent._effective_permissions()
