"""Tests for the non-blocking ask_user_async side-channel + Autopilot integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.askuser_channel import (
    all_entries,
    ask_question,
    clear,
    load,
    pending_questions,
    write_answer,
)
from shipit_agent.autopilot import Autopilot, BudgetPolicy
from shipit_agent.deep.goal_agent import Goal
from shipit_agent.tools.ask_user_async import AskUserAsyncTool
from shipit_agent.tools.base import ToolContext


@pytest.fixture(autouse=True)
def _isolated_channel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the ask_user channel to a tmp dir so tests don't collide."""
    monkeypatch.setenv("SHIPIT_ASKUSER_DIR", str(tmp_path / "askuser"))
    yield
    clear("test-run")


# ─────────────────────── channel primitives ───────────────────────


class TestChannelPrimitives:
    def test_new_channel_is_empty(self) -> None:
        ch = load("run-1")
        assert ch.entries == []

    def test_ask_then_load_roundtrip(self) -> None:
        ask_question(
            "run-1", "Which backend?", context="Need answer today", choices=["A", "B"]
        )
        ch = load("run-1")
        assert len(ch.entries) == 1
        assert ch.entries[0].question == "Which backend?"
        assert ch.entries[0].choices == ["A", "B"]
        assert not ch.entries[0].answered()

    def test_pending_ignores_answered(self) -> None:
        ask_question("run-1", "Q1")
        ask_question("run-1", "Q2")
        assert [e.question for e in pending_questions("run-1")] == ["Q1", "Q2"]
        write_answer("run-1", "answer-1")
        assert [e.question for e in pending_questions("run-1")] == ["Q1"]

    def test_write_answer_without_question_returns_false(self) -> None:
        assert write_answer("run-empty", "nope") is False

    def test_answer_preserves_previous_entries(self) -> None:
        ask_question("run-1", "Q1")
        ask_question("run-1", "Q2")
        write_answer("run-1", "A2")  # answers the latest
        entries = all_entries("run-1")
        assert entries[0].answered() is False  # Q1 still open
        assert entries[1].answer == "A2"

    def test_answer_by_index(self) -> None:
        ask_question("run-1", "Q1")
        ask_question("run-1", "Q2")
        write_answer("run-1", "A1", index=0)
        entries = all_entries("run-1")
        assert entries[0].answer == "A1"
        assert entries[1].answered() is False

    def test_clear_removes_file(self, tmp_path: Path) -> None:
        ask_question("gone-1", "X")
        clear("gone-1")
        assert load("gone-1").entries == []

    def test_safe_filename_defeats_traversal(self) -> None:
        # path traversal tokens get slugged to a safe filename
        ask_question("../../etc/passwd", "nope")
        entries = all_entries("../../etc/passwd")
        assert entries[0].question == "nope"


# ─────────────────────── the tool ───────────────────────


class TestAskUserAsyncTool:
    def test_rejects_empty_question(self) -> None:
        out = AskUserAsyncTool().run(
            ToolContext(prompt="demo", state={"autopilot_run_id": "r"})
        )
        assert "required" in out.text

    def test_queues_the_question(self) -> None:
        tool = AskUserAsyncTool()
        out = tool.run(
            ToolContext(prompt="demo", state={"autopilot_run_id": "r"}),
            question="Which SSO provider?",
            context="Need before we scope",
            choices=["Okta", "Auth0"],
        )
        assert out.metadata.get("awaiting_user") is True
        assert out.metadata.get("run_id") == "r"
        pending = pending_questions("r")
        assert len(pending) == 1 and pending[0].question == "Which SSO provider?"

    def test_run_id_falls_back_to_session(self) -> None:
        out = AskUserAsyncTool().run(
            ToolContext(prompt="demo", session_id="session-1"),
            question="Which?",
        )
        assert out.metadata.get("run_id") == "session-1"
        assert len(pending_questions("session-1")) == 1


# ─────────────────────── Autopilot integration ───────────────────────


@dataclass
class _Result:
    output: str = "ok"
    goal_status: str = "in_progress"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(
        default_factory=lambda: {"usage": {"total_tokens": 50}}
    )


class _QuietAgent:
    def __init__(self, outs: list[str]) -> None:
        self.outs = outs
        self.n = 0

    def run(self) -> _Result:
        i = min(self.n, len(self.outs) - 1)
        self.n += 1
        return _Result(output=self.outs[i], criteria_met=[False])


class TestAutopilotIntegration:
    def test_halts_into_awaiting_user_when_question_queued(
        self, tmp_path: Path
    ) -> None:
        rid = "ap-1"
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=5, max_seconds=30),
            agent_factory=lambda **_: _QuietAgent(["iter-output"]),
        )
        # Simulate the tool firing AFTER the first iteration runs by
        # queueing a question just before the loop check.
        # Here we simply pre-queue — Autopilot should pick it up on
        # iteration 1's tail.
        ask_question(rid, "Which SSO?")
        result = autopilot.run(run_id=rid)
        assert result.status == "awaiting_user"
        assert "ask_user_async" in result.halt_reason

    def test_resume_refuses_while_still_pending(self, tmp_path: Path) -> None:
        rid = "ap-2"
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=5),
            agent_factory=lambda **_: _QuietAgent(["iter-output"]),
        )
        ask_question(rid, "Which region?")
        first = autopilot.run(run_id=rid)
        assert first.status == "awaiting_user"

        # Resume without answering → still awaiting_user, zero extra iterations.
        resumed = autopilot.resume(rid)
        assert resumed.status == "awaiting_user"
        assert resumed.iterations == first.iterations

    def test_resume_after_answer_continues(self, tmp_path: Path) -> None:
        rid = "ap-3"
        autopilot = Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["a"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=3),
            agent_factory=lambda **_: _QuietAgent(["iter-output"]),
        )
        ask_question(rid, "Which region?")
        first = autopilot.run(run_id=rid)
        assert first.status == "awaiting_user"

        # User answers — resume should proceed past the awaiting gate.
        assert write_answer(rid, "us-east-1") is True
        resumed = autopilot.resume(rid)
        assert resumed.status != "awaiting_user"
