"""Shell commands: a two-minute default, and long work moves to the background.

A command that outlives its timeout used to raise mid-run, killing the work
and leaving its children behind. Now it keeps running as a background job
the model can check on, and a clipped result names the file that holds the
full output.
"""

from __future__ import annotations

import time
from pathlib import Path

from shipit_agent.tools.bash.bash_tool import BashJobTool, BashTool
from shipit_agent.tools.base import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(prompt="test")


def _bash(tmp_path: Path, **options) -> BashTool:
    return BashTool(root_dir=tmp_path, unrestricted=True, **options)


def test_the_default_timeout_is_two_minutes(tmp_path: Path) -> None:
    assert BashTool(root_dir=tmp_path).default_timeout == 120.0


def test_a_quick_command_returns_its_output(tmp_path: Path) -> None:
    out = _bash(tmp_path).run(_ctx(), command="echo hello && echo oops >&2")
    assert out.metadata["exit_code"] == 0
    assert "hello" in out.text and "oops" in out.text
    assert out.metadata.get("background") is not True


def test_a_failing_command_reports_its_exit_code(tmp_path: Path) -> None:
    out = _bash(tmp_path).run(_ctx(), command="exit 3")
    assert out.metadata["exit_code"] == 3


def test_a_command_past_its_timeout_continues_in_the_background(tmp_path: Path) -> None:
    bash = _bash(tmp_path)
    started = time.monotonic()
    out = bash.run(_ctx(), command="echo first; sleep 3; echo second", timeout=1)
    assert time.monotonic() - started < 2.5
    assert out.metadata["background"] is True
    assert out.metadata["timed_out"] is True
    assert "first" in out.text
    job_id = out.metadata["job_id"]

    deadline = time.monotonic() + 10
    status = bash.poll_job(job_id)
    while status["running"] and time.monotonic() < deadline:
        time.sleep(0.2)
        status = bash.poll_job(job_id)
    assert status["exit_code"] == 0
    assert "second" in status["output"]


def test_a_backgrounded_command_can_be_stopped(tmp_path: Path) -> None:
    bash = _bash(tmp_path)
    out = bash.run(_ctx(), command="sleep 30", timeout=1)
    jobs = BashJobTool(bash)
    stopped = jobs.run(_ctx(), job_id=out.metadata["job_id"], action="kill")
    assert stopped.metadata.get("killed") is True


def test_clipped_output_names_the_full_log(tmp_path: Path) -> None:
    out = _bash(tmp_path).run(_ctx(), command="seq 1 100000")
    assert "omitted" in out.text
    full = Path(out.metadata["stdout_path"])
    assert full.read_text().splitlines()[-1] == "100000"
    assert str(full) in out.text
