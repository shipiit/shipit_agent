"""The shell runs any command; risky ones need approval, a few never run.

An agent with no permission settings runs everyday commands freely. A risky
command (deleting, publishing, writing outside the project...) runs only
with an allow rule, bypass mode, or a yes from ``permission_callback``;
otherwise it is not run and the model is told why. Blocked commands never
run, whatever the settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shipit_agent import Agent
from shipit_agent.core.models import ToolCall
from shipit_agent.llms.base import LLMResponse
from shipit_agent.safety.permissions import PermissionDecision, PermissionResult
from shipit_agent.tools.bash.bash_tool import BashTool


class _RunsOnce:
    def __init__(self, command: str) -> None:
        self.command = command
        self.turn = 0

    def complete(self, **_: Any) -> LLMResponse:
        self.turn += 1
        if self.turn == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(name="bash", arguments={"command": self.command})],
            )
        return LLMResponse(content="done")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "keep.txt").write_text("precious")
    return tmp_path


def _run(project: Path, command: str, **options: Any) -> Any:
    agent = Agent(llm=_RunsOnce(command), tools=[BashTool(root_dir=project)], **options)
    return agent.run("go")


def _tool_message(result: Any) -> str:
    return next(m.content for m in result.messages if m.role == "tool")


def test_an_everyday_command_runs_without_settings(project: Path) -> None:
    result = _run(project, "seq 1 3 > nums.txt && cat nums.txt")
    assert (project / "nums.txt").read_text().split() == ["1", "2", "3"]
    assert "exit_code: 0" in _tool_message(result)


def test_a_risky_command_needs_approval_and_does_not_run(project: Path) -> None:
    result = _run(project, "rm keep.txt")
    assert (project / "keep.txt").exists()
    message = _tool_message(result)
    assert "requires" in message and "deletes files" in message


def test_a_yes_from_the_callback_runs_it(project: Path) -> None:
    asked: list[dict[str, Any]] = []

    def approve(name: str, arguments: dict[str, Any]) -> PermissionResult:
        asked.append(arguments)
        return PermissionResult(PermissionDecision.ALLOW, reason="user said yes")

    _run(project, "rm keep.txt", permission_callback=approve)
    assert not (project / "keep.txt").exists()
    assert asked == [{"command": "rm keep.txt"}]


def test_a_no_from_the_callback_keeps_it_from_running(project: Path) -> None:
    def refuse(name: str, arguments: dict[str, Any]) -> PermissionResult:
        return PermissionResult(PermissionDecision.DENY, reason="not today")

    result = _run(project, "rm keep.txt", permission_callback=refuse)
    assert (project / "keep.txt").exists()
    assert "not today" in _tool_message(result)


def test_an_allow_rule_runs_risky_commands(project: Path) -> None:
    _run(project, "rm keep.txt", permissions={"allow": ["bash"]})
    assert not (project / "keep.txt").exists()


def test_bypass_mode_runs_risky_commands(project: Path) -> None:
    _run(project, "rm keep.txt", permission_mode="bypass")
    assert not (project / "keep.txt").exists()


@pytest.mark.parametrize(
    "options", [{}, {"permission_mode": "bypass"}, {"permissions": {"allow": ["bash"]}}]
)
def test_a_blocked_command_never_runs(project: Path, options: dict[str, Any]) -> None:
    result = _run(project, "rm -rf ~", **options)
    assert "blocked" in _tool_message(result)


def test_a_callback_with_no_opinion_leaves_it_unapproved(project: Path) -> None:
    result = _run(
        project, "rm keep.txt", permission_callback=lambda name, arguments: None
    )
    assert (project / "keep.txt").exists()
    assert "requires" in _tool_message(result)
