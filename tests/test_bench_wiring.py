"""The benchmark's tasks all build, run and check without crashing.

With the echo model every outcome check should fail (it does no work), but
no task may raise: a crash there would surface only in a paid live run.
"""

from __future__ import annotations

import asyncio

import pytest

from scripts.bench.run import TASKS, build_llm, make_runner, run_task


@pytest.mark.parametrize("task", TASKS, ids=[t.name for t in TASKS])
def test_each_task_runs_and_is_checked(task) -> None:
    row = asyncio.run(run_task(task, make_runner(build_llm(None, None, dry_run=True))))
    assert not row["note"].split(":")[0].endswith(("Error", "Exception")), row["note"]
    assert row["passed"] is False  # the echo model does no work, so no check may pass


def test_task_names_are_unique() -> None:
    assert len({t.name for t in TASKS}) == len(TASKS) == 16


def test_a_check_after_an_edit_is_not_a_repeat() -> None:
    from scripts.bench.run import repeated_calls

    pytest_run = ("bash", {"command": "pytest"})
    edit = ("edit_file", {"path": "calc.py"})
    read = ("read_file", {"path": "calc.py"})
    assert repeated_calls([pytest_run, read, edit, pytest_run]) == 0
    assert repeated_calls([pytest_run, pytest_run]) == 1
    assert repeated_calls([read, ("glob_files", {"pattern": "*"}), read]) == 1
    assert repeated_calls([]) == 0


def _result(turns: int, prompt_tokens: int, cost: float, api_ms: int):
    from shipit_agent.sdk import ResultMessage

    return ResultMessage(subtype="success", duration_ms=api_ms, duration_api_ms=api_ms, is_error=False,
                         num_turns=turns, session_id="s", total_cost_usd=cost,
                         usage={"prompt_tokens": prompt_tokens, "completion_tokens": 5}, result=f"turn {turns}")


def test_a_task_of_several_turns_reports_all_of_them(tmp_path) -> None:
    from scripts.bench.run import _row
    from scripts.bench.tasks_basic import Run

    run = Run(root=tmp_path)
    run.record(_result(3, 1000, 0.01, 2000))
    run.record(_result(1, 400, 0.002, 500))
    row = _row(TASKS[0], run, True, "ok", 0.0)
    assert (row["turns"], row["input_tokens"], row["output_tokens"]) == (4, 1400, 10)
    assert row["cost_usd"] == 0.012 and row["api_ms"] == 2500
    assert run.answer == "turn 1"  # the answer is still the last turn's


def test_a_task_with_no_result_reports_zeros(tmp_path) -> None:
    from scripts.bench.run import _row
    from scripts.bench.tasks_basic import Run

    row = _row(TASKS[0], Run(root=tmp_path), False, "no result", 0.0)
    assert (row["turns"], row["input_tokens"], row["cost_usd"]) == (0, 0, None)


def test_the_recovery_task_states_the_id_format_only_in_its_error() -> None:
    from scripts.bench.tasks_hard import _order_status

    assert "ORD" not in _order_status.description


def _row_for(task: str, tokens: int, passed: bool = True) -> dict:
    return {"task": task, "passed": passed, "input_tokens": tokens, "output_tokens": 10, "turns": 2,
            "cost_usd": 0.01, "api_ms": 1000}


def test_compare_names_who_used_more_tokens() -> None:
    from scripts.bench.compare import compare

    a = ("gemma", {"t1": _row_for("t1", 1000), "t2": _row_for("t2", 3000)})
    b = ("claude", {"t1": _row_for("t1", 500), "t2": _row_for("t2", 9000, passed=False)})
    text = compare([a, b])
    assert "Most input tokens: claude, 2.38x gemma's." in text
    t1 = next(line for line in text.splitlines() if line.startswith("t1"))
    assert t1.rstrip().endswith("★")                      # claude's 500 is fewest
    t2 = next(line for line in text.splitlines() if line.startswith("t2"))
    assert "✗" in t2 and "★" in t2                         # a failed run cannot be the best


def test_compare_handles_a_task_missing_from_one_run() -> None:
    from scripts.bench.compare import compare

    text = compare([("a", {"t1": _row_for("t1", 10)}), ("b", {})])
    assert "t1" in text and " -" in text


def test_the_hook_task_gives_explicit_permission() -> None:
    # Without it, careful models ask first and the hook is never exercised.
    task = next(t for t in TASKS if t.name == "hook_blocks_delete")
    assert "permission" in task.prompt.lower() and "don't ask" in task.prompt.lower()


def test_recovery_passes_on_a_successful_retry_without_the_tracking_number(tmp_path) -> None:
    from scripts.bench.tasks_basic import Run

    task = next(t for t in TASKS if t.name == "tool_error_recovery")
    run = Run(root=tmp_path, answer="Order 42 shipped on 3 November.",
              tool_uses=[("orders__order_status", {"order_id": "42"}), ("orders__order_status", {"order_id": "ORD-42"})],
              tool_results=[("Invalid id", True), ("shipped on 2026-11-03, tracking ZX-9917", False)])
    assert task.check(run)[0]
    run.tool_results[1] = ("not found", False)
    assert not task.check(run)[0]  # a retry that did not succeed is not a recovery


def test_a_row_reports_what_the_model_wrote_beside_its_calls(tmp_path) -> None:
    from scripts.bench.run import _row
    from scripts.bench.tasks_basic import Run
    from shipit_agent.sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

    run = Run(root=tmp_path)
    run.record(AssistantMessage(content=[TextBlock(text="I'll run the tests."), ThinkingBlock(thinking="hm" * 50, signature=""),
                                         ToolUseBlock(id="1", name="bash", input={"command": "pytest"})], model="m"))
    row = _row(TASKS[0], run, True, "ok", 0.0)
    assert row["narration_chars"] == len("I'll run the tests.")
    assert row["thinking_chars"] == 100


def test_a_run_that_ended_in_error_reports_the_error(tmp_path) -> None:
    from scripts.bench.run import _row
    from scripts.bench.tasks_basic import Run
    from shipit_agent.sdk import ResultMessage

    run = Run(root=tmp_path)
    run.record(ResultMessage(subtype="error_during_execution", duration_ms=5, duration_api_ms=0, is_error=True,
                             num_turns=0, session_id="s", errors=["BadRequestError: model rejected the request"]))
    row = _row(TASKS[0], run, False, "answer lacks ['35']", 0.0)
    assert row["note"].startswith("run error: BadRequestError: model rejected")
    assert row["passed"] is False
