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
    assert len({t.name for t in TASKS}) == len(TASKS) == 12


def test_a_check_after_an_edit_is_not_a_repeat() -> None:
    from scripts.bench.run import repeated_calls

    pytest_run = ("bash", {"command": "pytest"})
    edit = ("edit_file", {"path": "calc.py"})
    read = ("read_file", {"path": "calc.py"})
    assert repeated_calls([pytest_run, read, edit, pytest_run]) == 0
    assert repeated_calls([pytest_run, pytest_run]) == 1
    assert repeated_calls([read, ("glob_files", {"pattern": "*"}), read]) == 1
    assert repeated_calls([]) == 0
