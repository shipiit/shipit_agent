"""``monitor``: the SDK's Monitor, run as a background command under bash's rules."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from shipit_agent import Agent
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.permission_rules import rule_matches, sdk_tool_name
from shipit_agent.sdk.options import DEFAULT_TOOLS
from shipit_agent.tools import BashTool, MonitorTool
from shipit_agent.tools.base import ToolContext


def _monitor(tmp_path: Path) -> tuple[BashTool, MonitorTool]:
    bash = BashTool(root_dir=str(tmp_path))
    return bash, MonitorTool(bash)


def _wait_until(check: Any, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.1)
    return False


def test_a_watch_is_a_background_task_with_a_deadline(tmp_path: Path) -> None:
    bash, monitor = _monitor(tmp_path)
    out = monitor.run(ToolContext(prompt=""), command="while true; do echo tick; sleep 0.2; done",
                      description="Watch ticks", timeout_ms=2500)
    body = json.loads(out.text)
    assert body["timeoutMs"] == 2500 and body["persistent"] is False and body["taskId"]
    tasks = {task.task_id: task for task in bash.list_background_tasks()}
    assert tasks[body["taskId"]].status == "running" and tasks[body["taskId"]].description == "Watch ticks"
    log = Path(tasks[body["taskId"]].output_file or "")
    assert _wait_until(lambda: "tick" in log.read_text())
    # The deadline stops it.
    assert _wait_until(lambda: {t.task_id: t for t in bash.list_background_tasks()}[body["taskId"]].status == "stopped")


def test_stopping_a_watch_early_works_like_any_background_task(tmp_path: Path) -> None:
    bash, monitor = _monitor(tmp_path)
    body = json.loads(monitor.run(ToolContext(prompt=""), command="sleep 30", description="Wait").text)
    stopped = bash.stop_background_task(body["taskId"])
    assert stopped is not None and stopped.status == "stopped"


@pytest.mark.parametrize(("given", "effective"), [(None, 300_000), (99_999_999, 1_800_000), (10, 1_000)])
def test_the_deadline_is_clamped(tmp_path: Path, given: Any, effective: int, monkeypatch: pytest.MonkeyPatch) -> None:
    bash, monitor = _monitor(tmp_path)
    started: list[float] = []
    monkeypatch.setattr(MonitorTool, "_stop_at_deadline", lambda self, job_id, seconds: started.append(seconds))
    arguments = {"command": "sleep 5", "description": "Wait"}
    if given is not None:
        arguments["timeout_ms"] = given
    body = json.loads(monitor.run(ToolContext(prompt=""), **arguments).text)
    assert body["timeoutMs"] == effective and started == [effective / 1000]
    bash.stop_background_task(body["taskId"])


@pytest.mark.parametrize(
    ("arguments", "words"),
    [
        ({"ws": {"url": "wss://x"}, "description": "d"}, "WebSocket"),
        ({"command": "echo hi", "ws": {"url": "wss://x"}, "description": "d"}, "exactly one"),
        ({"description": "d"}, "command"),
        ({"command": "echo hi"}, "description"),
        ({"command": ":", "description": "d"}, "rejected"),
    ],
)
def test_bad_watches_are_refused_without_starting_anything(tmp_path: Path, arguments: dict[str, Any], words: str) -> None:
    bash, monitor = _monitor(tmp_path)
    out = monitor.run(ToolContext(prompt=""), **arguments)
    assert out.metadata.get("is_error") is True and words in out.text
    assert bash.list_background_tasks() == []


def test_bash_rules_and_risk_checks_cover_monitor(tmp_path: Path) -> None:
    bash, monitor = _monitor(tmp_path)
    assert sdk_tool_name("Monitor") == "monitor" and "monitor" not in DEFAULT_TOOLS
    assert rule_matches("Bash(rm *)", "monitor", {"command": "rm -rf build"})
    assert rule_matches("Bash", "monitor", {"command": "tail -f log"})
    assert not rule_matches("Bash(rm *)", "monitor", {"command": "tail -f log"})
    risky = {"command": "rm -rf /etc"}
    assert monitor.assess_command(risky) == bash.assess_command(risky)


def test_an_agent_denied_a_bash_command_cannot_run_it_through_monitor(tmp_path: Path) -> None:
    class _Watches:
        model = "m"

        def __init__(self) -> None:
            self.turn = 0

        def complete(self, **_: Any) -> LLMResponse:
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(tool_calls=[ToolCall(name="monitor", id="m1",
                                                        arguments={"command": "sleep 30", "description": "Wait"})])
            return LLMResponse(content="done")

    bash, monitor = _monitor(tmp_path)
    result = Agent(llm=_Watches(), tools=[bash, monitor], disallowed_tools=["Bash(sleep *)"]).run("go")
    assert any(e.type == "tool_denied" for e in result.events)
    assert bash.list_background_tasks() == []
