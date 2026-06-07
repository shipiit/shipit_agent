"""Regression tests for autopilot fan-out result ordering (DEEP-2).

Children must come back in input (item-index) order, not lexicographic
run_id order — otherwise item 10/11 sort before item 2.
"""

from __future__ import annotations

from shipit_agent.autopilot.budget import BudgetPolicy
from shipit_agent.autopilot.core import Autopilot
from shipit_agent.autopilot.result import AutopilotResult
from shipit_agent.deep.goal_agent import Goal

# Import for side effect: attaches .fanout / .fanout_stream onto Autopilot.
import shipit_agent.autopilot.fanout  # noqa: F401


class _DummyLLM:
    def complete(self, **kwargs):  # pragma: no cover - never called
        raise AssertionError("LLM should not be called in this test")


def _make_autopilot() -> Autopilot:
    return Autopilot(
        llm=_DummyLLM(),
        goal=Goal(objective="x"),
        budget=BudgetPolicy(max_iterations=1),
        use_builtins=False,
    )


def _patch_child_run(monkeypatch, items):
    """Make every child return immediately, echoing its item index."""

    def fake_run(self, run_id=None, **kwargs):
        # run_id is f"{prid}.{slug}-{idx}"; recover idx from the suffix.
        idx = int(run_id.rsplit("-", 1)[1])
        return AutopilotResult(
            run_id=run_id,
            status="completed",
            output=str(items[idx]),
        )

    monkeypatch.setattr(Autopilot, "run", fake_run)


def test_fanout_preserves_input_order_with_double_digit_items(monkeypatch):
    items = list(range(12))  # 0..11 — lexicographic would put 10,11 before 2
    _patch_child_run(monkeypatch, items)
    ap = _make_autopilot()
    result = ap.fanout(items=items, objective_template="do {item}", max_parallel=4)
    outputs = [c["output"] for c in result.children]
    assert outputs == [str(i) for i in items]


def test_fanout_preserves_non_alphabetical_input_order(monkeypatch):
    items = ["zebra", "apple", "mango"]
    _patch_child_run(monkeypatch, items)
    ap = _make_autopilot()
    result = ap.fanout(items=items, objective_template="do {item}", max_parallel=3)
    outputs = [c["output"] for c in result.children]
    assert outputs == items


def test_fanout_stream_result_preserves_input_order(monkeypatch):
    items = list(range(12))
    _patch_child_run(monkeypatch, items)
    ap = _make_autopilot()
    events = list(
        ap.fanout_stream(items=items, objective_template="do {item}", max_parallel=4)
    )
    final = next(e for e in events if e["kind"] == "autopilot.fanout_result")
    outputs = [c["output"] for c in final["children"]]
    assert outputs == [str(i) for i in items]
